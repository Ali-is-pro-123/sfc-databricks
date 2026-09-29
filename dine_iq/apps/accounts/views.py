"""Authentication and administrator-managed account registration."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from apps.restaurants.models import LocationAccess

from .forms import AccountAccessForm, AccountCreationForm, SignInForm
from .models import User
from .permissions import administrator_required


class SignInView(LoginView):
    template_name = "accounts/login.html"
    authentication_form = SignInForm
    redirect_authenticated_user = True


@login_required
def home(request):
    return render(request, "accounts/home.html")


@administrator_required
def account_list(request):
    accounts = User.objects.annotate(location_count=Count("locationaccess")).order_by("username")
    page = Paginator(accounts, 25).get_page(request.GET.get("page"))
    return render(request, "accounts/list.html", {"page_obj": page})


@administrator_required
@require_http_methods(["GET", "POST"])
def account_create(request):
    form = AccountCreationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            user = form.save()
            LocationAccess.objects.bulk_create(
                LocationAccess(user=user, restaurant=location)
                for location in form.cleaned_data["locations"]
            )
        messages.success(request, f"Account created for {user.username}.")
        return redirect("accounts:list")
    return render(request, "accounts/create.html", {"form": form})


@administrator_required
@require_http_methods(["GET", "POST"])
def account_access(request, pk):
    account = get_object_or_404(User, pk=pk)
    initial = {
        "role": account.role,
        "locations": list(LocationAccess.objects.filter(user=account).values_list("restaurant_id", flat=True)),
    }
    form = AccountAccessForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        if account.pk == request.user.pk and form.cleaned_data["role"] != account.role:
            form.add_error("role", "You cannot change your own role.")
        else:
            with transaction.atomic():
                account.role = form.cleaned_data["role"]
                account.save(update_fields=["role"])
                LocationAccess.objects.filter(user=account).delete()
                LocationAccess.objects.bulk_create(
                    LocationAccess(user=account, restaurant=location)
                    for location in form.cleaned_data["locations"]
                )
            messages.success(request, f"Access updated for {account.username}.")
            return redirect("accounts:list")
    return render(request, "accounts/access.html", {"form": form, "account": account})
