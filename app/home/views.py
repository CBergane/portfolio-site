import logging
import os
import time

import requests
from django.conf import settings
from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_http_methods
from django_ratelimit.decorators import ratelimit

from .contact_security import contact_ratelimit_key, get_client_ip


logger = logging.getLogger(__name__)


def verify_turnstile(token: str | None, client_ip: str) -> bool:
    """Verify the contact challenge's success, hostname and action."""
    if not token or len(token) > 2048 or not settings.TURNSTILE_SECRET_KEY:
        return False

    try:
        response = requests.post(
            "https://challenges.cloudflare.com/turnstile/v0/siteverify",
            data={
                "secret": settings.TURNSTILE_SECRET_KEY,
                "response": token,
                "remoteip": client_ip,
            },
            timeout=5,
        )
        response.raise_for_status()
        result = response.json()
    except (requests.RequestException, ValueError):
        return False

    return (
        isinstance(result, dict)
        and result.get("success") is True
        and result.get("hostname") == "cbergane.se"
        and result.get("action") == "contact"
    )


def send_discord_notification(submission) -> bool:
    """
    Send contact form submission to Discord webhook
    """
    webhook_url = os.getenv('DISCORD_WEBHOOK_URL')
    
    if not webhook_url:
        logger.info('Discord webhook notification skipped', extra={
            'event': 'discord_webhook', 'outcome': 'not_configured',
        })
        return False
    
    embed = {
        "title": "📬 New Contact Form Submission",
        "color": 0x9fef00,
        "fields": [
            {"name": "👤 Name", "value": submission.name, "inline": True},
            {"name": "📧 Email", "value": submission.email, "inline": True},
            {"name": "📝 Subject", "value": submission.subject or "No subject", "inline": False},
            {"name": "💬 Message", "value": submission.message[:1000], "inline": False},
            {"name": "🕐 Submitted", "value": submission.submitted_at.strftime("%Y-%m-%d %H:%M:%S"), "inline": True},
            {"name": "🌐 IP Address", "value": submission.ip_address or "Unknown", "inline": True}
        ],
        "footer": {"text": "Portfolio Contact Form"}
    }
    
    payload = {"username": "Portfolio Bot", "embeds": [embed]}
    
    try:
        response = requests.post(webhook_url, json=payload, timeout=10)
        response.raise_for_status()
        logger.info('Discord webhook notification sent', extra={
            'event': 'discord_webhook', 'outcome': 'sent',
        })
        return True
    except requests.exceptions.RequestException as exc:
        # Exception text and request/response objects can contain webhook secrets.
        logger.warning('Discord webhook notification failed', extra={
            'event': 'discord_webhook', 'outcome': 'failed',
            'error_type': type(exc).__name__,
        })
        return False


@require_http_methods(["POST"])
@ratelimit(
    key=contact_ratelimit_key,
    rate="3/h",
    method="POST",
    block=False,
)
def contact_form_submit(request: HttpRequest) -> JsonResponse:
    """
    Handle contact form submission with rate limiting
    """
    
    from .forms import ContactForm

    success_payload = {
        'success': True,
        'message': 'Thank you! Your message has been sent.',
    }

    # Silently discard obvious bot submissions caught by the honeypot.
    if request.POST.get("website", "").strip():
        return JsonResponse(success_payload)
    
    # Check rate limit
    if getattr(request, 'limited', False):
        return JsonResponse({
            'success': False,
            'errors': {'__all__': ['Too many requests. Please try again in an hour.']}
        }, status=429)
    
    # Session cooldown
    last_submission = request.session.get('last_contact_submission', 0)
    current_time = time.time()
    cooldown_period = 300  # 5 minutes
    
    if current_time - last_submission < cooldown_period:
        time_remaining = int(cooldown_period - (current_time - last_submission))
        minutes = time_remaining // 60
        return JsonResponse({
            'success': False,
            'errors': {'__all__': [f'Please wait {minutes} minutes before submitting again.']}
        }, status=429)
    
    form = ContactForm(request.POST)
    
    if not form.is_valid():
        return JsonResponse({
            'success': False,
            'errors': form.errors
        }, status=400)

    client_ip = get_client_ip(request)
    token = request.POST.get('cf-turnstile-response', '').strip()
    if not verify_turnstile(token, client_ip):
        return JsonResponse({
            'success': False,
            'errors': {'__all__': ['Verification failed. Please try again.']},
        }, status=400)

    submission = form.save(commit=False)
    # Use the same trusted client-IP resolution as rate limiting.
    submission.ip_address = client_ip or None
    submission.user_agent = request.META.get('HTTP_USER_AGENT', '')
    submission.save()
    request.session['last_contact_submission'] = current_time
    send_discord_notification(submission)
    return JsonResponse(success_payload)
