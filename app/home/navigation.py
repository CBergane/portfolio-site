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


def adjacent_content(request, current_page, destinations=None):
    """Older/newer public entries owned by the same resolved index and Site.

    Legacy sibling details use the same fallback as their back-to-index link.
    Nested indexes own their descendants; nested Sites are excluded upstream.
    """
    from django.db.models import F
    from .models import BlogIndexPage, BlogPage, ProjectIndexPage, ProjectPage

    empty = {'previous': None, 'next': None}
    if isinstance(current_page, BlogPage):
        model, index_model, key = BlogPage, BlogIndexPage, 'notes'
    elif isinstance(current_page, ProjectPage):
        model, index_model, key = ProjectPage, ProjectIndexPage, 'work'
    else:
        return empty
    destinations = destinations or site_destinations(request, current_page)
    index = destinations.get(key)
    site = site_for_request(request)
    if not index or not site:
        return empty
    indexes = list(public_site_pages(index_model, request).exclude(
        pk=site.root_page_id
    ).order_by('path').values('pk', 'path'))
    if not indexes:
        return empty

    def owner(path):
        ancestors = [item for item in indexes if path.startswith(item['path'])]
        return max(ancestors, key=lambda item: len(item['path']))['pk'] if ancestors else indexes[0]['pk']

    pages = public_site_pages(model, request).defer_streamfields().select_related('content_type').order_by(
        'date', F('first_published_at').asc(nulls_first=True), 'pk'
    )
    entries = [entry for entry in pages if owner(entry.path) == index.pk]
    for position, entry in enumerate(entries):
        if entry.pk == current_page.pk:
            return {
                'previous': entries[position - 1] if position else None,
                'next': entries[position + 1] if position + 1 < len(entries) else None,
            }
    return empty
