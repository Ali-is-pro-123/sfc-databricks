"""Validated forms for signing in and provisioning accounts."""

from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django import forms

from apps.restaurants.models import Restaurant

from .models import User


class StyledFields:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field.widget, forms.CheckboxSelectMultiple):
                field.widget.attrs["class"] = "accent-orange-600"
            else:
                field.widget.attrs["class"] = (
                    "theme-field w-full rounded-lg border bg-white px-3 py-2"
                )


class SignInForm(StyledFields, AuthenticationForm):
    pass


def location_field():
    return forms.ModelMultipleChoiceField(
        queryset=Restaurant.objects.filter(is_active=True).order_by("city", "name"),
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label="Assigned locations",
        help_text="Required for Restaurant and Regional Managers. Administrators and Analysts can see all locations automatically.",
    )


class LocationAssignmentFields:

    def clean(self):
        cleaned_data = super().clean()
        role = cleaned_data.get("role")
        locations = cleaned_data.get("locations")
        if role in (User.Role.RESTAURANT_MANAGER, User.Role.REGIONAL_MANAGER):
            if not locations:
                self.add_error("locations", "Select at least one location for a manager.")
        elif role in (User.Role.ADMINISTRATOR, User.Role.ANALYST) and locations:
            self.add_error("locations", "This role already has access to all locations; leave assignments empty.")
        return cleaned_data


class AccountCreationForm(LocationAssignmentFields, StyledFields, UserCreationForm):
    locations = location_field()

    class Meta(UserCreationForm.Meta):
        model = User
        # Business administrators cannot grant Django staff or superuser flags.
        fields = ("username", "first_name", "last_name", "email", "role")


class AccountAccessForm(LocationAssignmentFields, StyledFields, forms.Form):
    role = forms.ChoiceField(choices=User.Role.choices)
    locations = location_field()
