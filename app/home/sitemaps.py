"""Sitemaps follow the same public Site boundary as the portfolio navigation."""
from wagtail.contrib.sitemaps import Sitemap
from wagtail.models import Page

from .navigation import public_site_pages
from .seo import public_url


class PublicPageSitemap(Sitemap):
    def items(self):
        return public_site_pages(Page, self.request).order_by('path').defer_streamfields().specific()

    def get_urls(self, page=1, site=None, protocol=None):
        urls = super().get_urls(page=page, site=site, protocol=protocol)
        for item in urls:
            item['location'] = public_url(self.request, item['location'])
        return urls
