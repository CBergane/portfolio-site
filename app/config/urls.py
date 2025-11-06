from django.conf import settings
from django.urls import path, include
from django.contrib import admin
from django.http import HttpResponse
from django.views.decorators.http import require_safe

from wagtail.admin import urls as wagtailadmin_urls
from wagtail import urls as wagtail_urls
from wagtail.documents import urls as wagtaildocs_urls
from wagtail.contrib.sitemaps.views import sitemap

from home.views import htb_stats, contact_form_submit

# Minimal och snabb hälsokontroll (GET/HEAD). Låg overhead, plain text.
@require_safe
def healthz(_request):
    return HttpResponse("OK", content_type="text/plain")

urlpatterns = [
    # Admin/CMS
    path('secret-django-control/', admin.site.urls),
    path('cms-backend-2025/', include(wagtailadmin_urls)),

    # API/verktyg
    path('documents/', include(wagtaildocs_urls)),
    path('api/htb-stats', htb_stats, name='htb_stats'),
    path('api/contact-submit', contact_form_submit, name='contact_submit'),
    path('sitemap.xml', sitemap, name='sitemap'),

    # Hälsa – måste ligga FÖRE wagtail_urls
    path('healthz', healthz, name='healthz'),

    # Wagtail pages sist
    path('', include(wagtail_urls)),
]

if settings.DEBUG:
    from django.conf.urls.static import static
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
