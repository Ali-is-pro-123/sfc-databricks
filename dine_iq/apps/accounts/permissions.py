"""Reusable server-side authorization for account administration."""

from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied


def administrator_required(view):
    @login_required
    @wraps(view)
    def guarded(request, *args, **kwargs):
        if not request.user.can_manage_accounts:
            raise PermissionDenied
        return view(request, *args, **kwargs)

    return guarded
