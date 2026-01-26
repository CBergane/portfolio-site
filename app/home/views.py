from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django_ratelimit.decorators import ratelimit
import requests
import os

from .htb import get_htb_profile


@require_http_methods(["GET"])
def htb_stats(request):
    """
    Simple HTMX endpoint
    """
    return JsonResponse(get_htb_profile(request))


def send_discord_notification(submission):
    """
    Send contact form submission to Discord webhook
    """
    webhook_url = os.getenv('DISCORD_WEBHOOK_URL')
    
    if not webhook_url:
        print("⚠️ No Discord webhook URL configured")
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
        print(f"✅ Discord notification sent for submission from {submission.name}")
        return True
    except requests.exceptions.RequestException as e:
        print(f"❌ Failed to send Discord notification: {e}")
        return False


@require_http_methods(["POST"])
@ratelimit(key='ip', rate='3/h', method='POST', block=True)
def contact_form_submit(request):
    """
    Handle contact form submission with rate limiting
    """
    print("🔥 CONTACT FORM CALLED!")  # Debug
    
    from .forms import ContactForm
    from .models import ContactSubmission
    import time
    
    # DEBUG
    print("="*50)
    print(f"Request IP: {request.META.get('REMOTE_ADDR')}")
    print(f"Rate limited: {getattr(request, 'limited', False)}")
    print(f"Session key: {request.session.session_key}")
    print(f"Last submission: {request.session.get('last_contact_submission', 'Never')}")
    print("="*50)
    
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
    
    if form.is_valid():
        submission = form.save(commit=False)
        
        # Get IP
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            submission.ip_address = x_forwarded_for.split(',')[0]
        else:
            submission.ip_address = request.META.get('REMOTE_ADDR')
        
        submission.user_agent = request.META.get('HTTP_USER_AGENT', '')
        submission.save()
        
        # Update session
        request.session['last_contact_submission'] = current_time
        
        # Send Discord
        send_discord_notification(submission)
        
        return JsonResponse({
            'success': True,
            'message': 'Thank you! Your message has been sent.'
        })
    else:
        return JsonResponse({
            'success': False,
            'errors': form.errors
        }, status=400)
