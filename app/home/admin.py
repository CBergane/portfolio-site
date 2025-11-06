from django.contrib import admin
from .models import ContactSubmission


@admin.register(ContactSubmission)
class ContactSubmissionAdmin(admin.ModelAdmin):
    list_display = ['name', 'email', 'subject', 'submitted_at', 'read', 'replied']
    list_filter = ['read', 'replied', 'submitted_at']
    search_fields = ['name', 'email', 'subject', 'message']
    readonly_fields = ['name', 'email', 'subject', 'message', 'submitted_at', 'ip_address', 'user_agent']
    
    def has_add_permission(self, request):
        return False  # Can't add submissions manually