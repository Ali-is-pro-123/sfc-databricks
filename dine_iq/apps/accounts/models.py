"""Application users and their business roles."""

from django.contrib.auth.models import AbstractUser, UserManager
from django.db import models


class AccountManager(UserManager):
    def create_superuser(self, username, email=None, password=None, **extra_fields):
        extra_fields.setdefault("role", "administrator")
        return super().create_superuser(username, email, password, **extra_fields)


class User(AbstractUser):
    class Role(models.TextChoices):
        ADMINISTRATOR = "administrator", "Administrator"
        RESTAURANT_MANAGER = "restaurant_manager", "Restaurant Manager"
        REGIONAL_MANAGER = "regional_manager", "Regional Manager"
        ANALYST = "analyst", "Analyst"

    role = models.CharField(max_length=24, choices=Role.choices, default=Role.ANALYST)
    objects = AccountManager()

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(role__in=[
                    "administrator", "restaurant_manager", "regional_manager", "analyst"
                ]),
                name="accounts_user_valid_role",
            )
        ]

    @property
    def can_manage_accounts(self):
        return self.is_active and (self.is_superuser or self.role == self.Role.ADMINISTRATOR)
