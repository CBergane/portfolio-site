"""Keep public URLs on their Wagtail host behind an HTTPS reverse proxy."""


def public_url(request, url):
    # Site.port may be 80 even when the trusted proxy serves HTTPS.
    if url and request.is_secure() and url.startswith('http://'):
        return 'https://' + url.removeprefix('http://')
    return url
