"""Query boundaries shared by location pages and future analytics endpoints."""

from apps.accounts.models import User

from .models import Restaurant


def visible_restaurants(user):
    locations = Restaurant.objects.all()
    if not user.is_authenticated or not user.is_active:
        return locations.none()
    if user.is_superuser or user.role in (User.Role.ADMINISTRATOR, User.Role.ANALYST):
        return locations
    if user.role in (User.Role.RESTAURANT_MANAGER, User.Role.REGIONAL_MANAGER):
        return locations.filter(access_grants__user=user)
    return locations.none()
