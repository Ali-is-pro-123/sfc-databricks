"""Authentication and administrator-managed account registration."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.core.paginator import Paginator
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from .forms import AccountCreationForm, SignInForm
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
    page = Paginator(User.objects.order_by("username"), 25).get_page(request.GET.get("page"))
    return render(request, "accounts/list.html", {"page_obj": page})


@administrator_required
@require_http_methods(["GET", "POST"])
def account_create(request):
    form = AccountCreationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        messages.success(request, f"Account created for {user.username}.")
        return redirect("accounts:list")
    return render(request, "accounts/create.html", {"form": form})
