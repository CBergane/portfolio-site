import ipaddress

from django.conf import settings


def _parse_ip(value):
    try:
        return ipaddress.ip_address((value or "").strip())
    except ValueError:
        return None


def _trusted_proxy_networks():
    networks = getattr(
        settings,
        "CONTACT_TRUSTED_PROXY_NETWORKS",
        ("127.0.0.0/8", "::1/128", "10.89.0.0/16"),
    )
    return tuple(ipaddress.ip_network(network) for network in networks)


def get_client_ip(request):
    """Resolve the client IP while trusting forwarded headers only from known proxies."""
    remote_ip = _parse_ip(request.META.get("REMOTE_ADDR"))

    if not remote_ip:
        return ""

    trusted_networks = _trusted_proxy_networks()

    if not any(remote_ip in network for network in trusted_networks):
        return str(remote_ip)

    forwarded_ips = [
        parsed
        for value in request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")
        if (parsed := _parse_ip(value))
    ]

    # Walk from the proxy closest to Django back towards the client.
    # Ignore addresses belonging to trusted proxy networks.
    for forwarded_ip in reversed(forwarded_ips):
        if not any(
            forwarded_ip in network
            for network in trusted_networks
        ):
            return str(forwarded_ip)

    return str(remote_ip)


def contact_ratelimit_key(_group, request):
    return get_client_ip(request) or "unknown"
