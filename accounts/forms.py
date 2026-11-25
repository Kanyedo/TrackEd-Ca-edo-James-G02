from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm

from .models import AccountProfile

User = get_user_model()


class RegistrationForm(UserCreationForm):
    email = forms.EmailField()
    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150)

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "first_name", "last_name", "email")

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("An account with this username already exists.")
        return username

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email


class ProfileUserForm(forms.ModelForm):
    email = forms.EmailField()
    # Required here even though Django's User model allows blank names, so a
    # profile save cannot wipe out the user's name.
    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150)

    class Meta:
        model = User
        fields = ("first_name", "last_name", "email")

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email


class ProfileDetailsForm(forms.ModelForm):
    class Meta:
        model = AccountProfile
        fields = ("phone_number", "school_name")
        help_texts = {"phone_number": "Optional. For example 0917 123 4567."}

    def clean_phone_number(self):
        return self.cleaned_data["phone_number"].strip()

    def clean_school_name(self):
        return self.cleaned_data["school_name"].strip()
