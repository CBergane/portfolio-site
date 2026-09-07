"""Public page discovery within the current Wagtail Site's ownership boundary."""

from wagtail.models import Site


def site_for_request(request):
    return Site.find_for_request(request) if request is not None else None


def public_site_pages(model, request):
    site = site_for_request(request)
    if not site:
        return model.objects.none()
    root = site.root_page
    pages = model.objects.live().public().descendant_of(root, inclusive=True)
    # A nested Site owns its subtree, even when it is beneath this root.
    for path in Site.objects.exclude(pk=site.pk).filter(
        root_page__path__startswith=root.path
    ).exclude(root_page_id=root.pk).values_list('root_page__path', flat=True):
        pages = pages.exclude(path__startswith=path)
    return pages


def site_destinations(request, current_page=None):
    from .models import BlogIndexPage, ContactPage, ProjectIndexPage

    site = site_for_request(request)
    destinations = {'root': site.root_page if site else None}
    for name, model in (
        ('work', ProjectIndexPage), ('notes', BlogIndexPage), ('contact', ContactPage),
    ):
        candidates = public_site_pages(model, request).order_by('path')
        # An index label must never lead to the Site root, even if that root
        # itself has an index type. Ownership/public filtering applies to both
        # the ancestor preference and the fallback for legacy sibling details.
        if site and name in ('work', 'notes'):
            candidates = candidates.exclude(pk=site.root_page_id)
        branch = (
            candidates.ancestor_of(current_page, inclusive=True).order_by('-depth').first()
            if current_page else None
        )
        destinations[name] = branch or candidates.first()
    return destinations
