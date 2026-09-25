"""Validated forms for signing in and provisioning accounts."""

from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

from .models import User


class StyledFields:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = (
                "theme-field w-full rounded-lg border bg-white px-3 py-2"
            )


class SignInForm(StyledFields, AuthenticationForm):
    pass


class AccountCreationForm(StyledFields, UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        # Business administrators cannot grant Django staff or superuser flags.
        fields = ("username", "first_name", "last_name", "email", "role")
