from django import forms
from .models import ContactSubmission


class ContactForm(forms.ModelForm):
    """
    Contact form with validation
    """
    class Meta:
        model = ContactSubmission
        fields = ['name', 'email', 'subject', 'message']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'w-full px-4 py-3 bg-htb-gray border border-htb-green/30 rounded-lg text-gray-100 placeholder-gray-500 focus:outline-none focus:border-htb-green transition-colors',
                'placeholder': 'Your name'
            }),
            'email': forms.EmailInput(attrs={
                'class': 'w-full px-4 py-3 bg-htb-gray border border-htb-green/30 rounded-lg text-gray-100 placeholder-gray-500 focus:outline-none focus:border-htb-green transition-colors',
                'placeholder': 'your.email@example.com'
            }),
            'subject': forms.TextInput(attrs={
                'class': 'w-full px-4 py-3 bg-htb-gray border border-htb-green/30 rounded-lg text-gray-100 placeholder-gray-500 focus:outline-none focus:border-htb-green transition-colors',
                'placeholder': 'Subject (optional)'
            }),
            'message': forms.Textarea(attrs={
                'class': 'w-full px-4 py-3 bg-htb-gray border border-htb-green/30 rounded-lg text-gray-100 placeholder-gray-500 focus:outline-none focus:border-htb-green transition-colors',
                'placeholder': 'Your message...',
                'rows': 6
            }),
        }
    
    def clean_message(self):
        message = self.cleaned_data.get('message')
        if len(message) < 10:
            raise forms.ValidationError('Message must be at least 10 characters long.')
        return message