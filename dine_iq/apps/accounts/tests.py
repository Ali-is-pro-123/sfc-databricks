"""Exercise authentication and authorization through HTTP requests."""

from django.conf import settings
from django.contrib.staticfiles import finders
from django.db import IntegrityError, transaction
from django.test import Client, TestCase
from django.urls import reverse

from apps.restaurants.access import visible_restaurants
from apps.restaurants.models import LocationAccess, Restaurant

from .models import User


class AccountTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.password = "Test-only-strong-password-693!"
        cls.users = {
            role: User.objects.create_user(role, password=cls.password, role=role)
            for role in User.Role.values
        }
        cls.location = Restaurant.objects.create(code="ACCOUNT-R1", name="Central", city="Karachi")
        cls.other_location = Restaurant.objects.create(code="ACCOUNT-R2", name="North", city="Lahore")

    def test_anonymous_pages_require_login(self):
        for name in ("home", "list", "create"):
            with self.subTest(name=name):
                response = self.client.get(reverse(f"accounts:{name}"))
                self.assertEqual(response.status_code, 302)
                self.assertIn(reverse("accounts:login"), response.url)

    def test_role_access_matrix(self):
        for role, user in self.users.items():
            with self.subTest(role=role):
                self.client.force_login(user)
                self.assertEqual(self.client.get(reverse("accounts:home")).status_code, 200)
                expected = 200 if role == User.Role.ADMINISTRATOR else 403
                for name in ("list", "create"):
                    self.assertEqual(self.client.get(reverse(f"accounts:{name}")).status_code, expected)
                if expected == 403:
                    self.assertEqual(self.client.post(reverse("accounts:create"), {}).status_code, 403)
                self.assertEqual(self.client.get(reverse("accounts:access", args=[user.pk])).status_code, expected)

    def test_login_and_post_logout(self):
        response = self.client.post(reverse("accounts:login"), {
            "username": "analyst", "password": self.password,
        })
        self.assertRedirects(response, reverse("accounts:home"))
        self.assertIn("_auth_user_id", self.client.session)
        self.assertEqual(self.client.get(reverse("accounts:logout")).status_code, 405)
        self.assertRedirects(self.client.post(reverse("accounts:logout")), reverse("accounts:login"))
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_external_redirect_is_rejected(self):
        response = self.client.post(reverse("accounts:login"), {
            "username": "analyst", "password": self.password,
            "next": "https://example.org/steal-session",
        })
        self.assertRedirects(response, reverse("accounts:home"))

    def test_wrong_password_and_inactive_account_rejected(self):
        for password, active in (("wrong-password", True), (self.password, False)):
            User.objects.filter(username="analyst").update(is_active=active)
            response = self.client.post(reverse("accounts:login"), {
                "username": "analyst", "password": password,
            })
            self.assertEqual(response.status_code, 200)
            self.assertNotIn("_auth_user_id", self.client.session)

    def test_deactivated_session_loses_access(self):
        self.client.force_login(self.users[User.Role.ADMINISTRATOR])
        User.objects.filter(role=User.Role.ADMINISTRATOR).update(is_active=False)
        self.assertEqual(self.client.get(reverse("accounts:list")).status_code, 302)

    def account_payload(self, **changes):
        payload = {
            "username": "new_manager", "role": User.Role.RESTAURANT_MANAGER,
            "password1": self.password, "password2": self.password,
            "locations": [self.location.pk],
        }
        return payload | changes

    def test_administrator_creates_hashed_password_without_privilege_flags(self):
        self.client.force_login(self.users[User.Role.ADMINISTRATOR])
        response = self.client.post(reverse("accounts:create"), self.account_payload(
            is_staff="on", is_superuser="on",
        ))
        self.assertRedirects(response, reverse("accounts:list"))
        user = User.objects.get(username="new_manager")
        self.assertTrue(user.check_password(self.password))
        self.assertNotEqual(user.password, self.password)
        self.assertFalse(user.is_superuser)
        self.assertFalse(user.is_staff)
        self.assertEqual(list(visible_restaurants(user)), [self.location])

    def test_manager_creation_requires_location_and_global_roles_reject_grants(self):
        self.client.force_login(self.users[User.Role.ADMINISTRATOR])
        response = self.client.post(reverse("accounts:create"), self.account_payload(locations=[]))
        self.assertContains(response, "Select at least one location")
        self.assertFalse(User.objects.filter(username="new_manager").exists())
        response = self.client.post(reverse("accounts:create"), self.account_payload(role=User.Role.ANALYST))
        self.assertContains(response, "already has access to all locations")
        self.assertFalse(User.objects.filter(username="new_manager").exists())

    def test_admin_can_update_existing_manager_scope_and_role(self):
        admin = self.users[User.Role.ADMINISTRATOR]
        manager = self.users[User.Role.RESTAURANT_MANAGER]
        self.client.force_login(admin)
        url = reverse("accounts:access", args=[manager.pk])
        self.assertContains(self.client.get(url), "Assigned locations")
        self.assertRedirects(self.client.post(url, {
            "role": User.Role.RESTAURANT_MANAGER,
            "locations": [self.location.pk, self.other_location.pk],
        }), reverse("accounts:list"))
        self.assertEqual(set(visible_restaurants(manager)), {self.location, self.other_location})
        self.assertRedirects(self.client.post(url, {
            "role": User.Role.RESTAURANT_MANAGER,
            "locations": [self.other_location.pk],
        }), reverse("accounts:list"))
        self.assertEqual(list(visible_restaurants(manager)), [self.other_location])
        self.assertRedirects(self.client.post(url, {"role": User.Role.ANALYST}), reverse("accounts:list"))
        manager.refresh_from_db()
        self.assertEqual(manager.role, User.Role.ANALYST)
        self.assertFalse(LocationAccess.objects.filter(user=manager).exists())
        self.assertEqual(set(visible_restaurants(manager)), {self.location, self.other_location})

    def test_admin_cannot_change_own_role(self):
        admin = self.users[User.Role.ADMINISTRATOR]
        self.client.force_login(admin)
        response = self.client.post(reverse("accounts:access", args=[admin.pk]), {
            "role": User.Role.ANALYST,
        })
        self.assertContains(response, "cannot change your own role")
        admin.refresh_from_db()
        self.assertEqual(admin.role, User.Role.ADMINISTRATOR)

    def test_manage_data_uses_product_page_not_admin_index(self):
        self.client.force_login(self.users[User.Role.ADMINISTRATOR])
        response = self.client.get(reverse("data_management"))
        self.assertContains(response, "Manage data")
        self.assertContains(response, "Advanced record editor")
        self.assertContains(response, f'href="{reverse("data_management")}"')
        self.client.force_login(self.users[User.Role.ANALYST])
        self.assertEqual(self.client.get(reverse("data_management")).status_code, 403)

    def test_invalid_registration_does_not_create_user(self):
        self.client.force_login(self.users[User.Role.ADMINISTRATOR])
        cases = [
            {"role": "unknown"}, {"password2": "mismatch"},
            {"password1": "123", "password2": "123"}, {"username": "analyst"},
        ]
        for change in cases:
            with self.subTest(change=change):
                response = self.client.post(reverse("accounts:create"), self.account_payload(**change))
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context["form"].errors)
                self.assertEqual(User.objects.count(), 4)

    def test_csrf_required_on_all_mutating_routes(self):
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(client.post(reverse("accounts:login"), {}).status_code, 403)
        client.force_login(self.users[User.Role.ADMINISTRATOR])
        for name in ("create", "logout"):
            self.assertEqual(client.post(reverse(f"accounts:{name}"), {}).status_code, 403)
        client.get(reverse("accounts:create"))
        response = client.post(reverse("accounts:create"), self.account_payload(),
                               HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value)
        self.assertEqual(response.status_code, 302)

    def test_role_change_applies_to_existing_session(self):
        user = self.users[User.Role.ADMINISTRATOR]
        self.client.force_login(user)
        User.objects.filter(pk=user.pk).update(role=User.Role.ANALYST)
        self.assertEqual(self.client.get(reverse("accounts:list")).status_code, 403)

    def test_superuser_creation_defaults_to_administrator(self):
        user = User.objects.create_superuser("owner", password=self.password)
        self.assertEqual(user.role, User.Role.ADMINISTRATOR)
        self.assertTrue(user.can_manage_accounts)
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse("admin:accounts_user_add")).status_code, 200)

    def test_staff_with_user_permission_cannot_escalate_in_admin(self):
        from django.contrib.auth.models import Permission

        user = self.users[User.Role.ANALYST]
        user.is_staff = True
        user.save()
        user.user_permissions.add(Permission.objects.get(codename="change_user", content_type__app_label="accounts"))
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse("admin:accounts_user_change", args=[user.pk])).status_code, 403)

    def test_database_rejects_unknown_role(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.create_user("invalid", role="invalid")

    def test_theme_preserves_login_form_and_static_assets(self):
        response = self.client.get(reverse("accounts:login") + "?next=/dashboard/")
        self.assertContains(response, 'class="entry-layout"')
        self.assertContains(response, 'name="next" value="/dashboard/"')
        self.assertContains(response, '/static/css/theme.css')
        self.assertContains(response, '/static/assets/dineiq-logo.png')
        self.assertContains(response, 'rel="icon" href="/static/assets/dineiq-logo.png?v=2" type="image/png"')
        for asset in ("assets/brand.svg", "assets/dineiq-logo.png", "assets/restaurant-table.png", "assets/Geometric-Book.otf"):
            with self.subTest(asset=asset):
                self.assertIsNotNone(finders.find(asset))

    def test_theme_keeps_role_gated_navigation(self):
        self.client.force_login(self.users[User.Role.ANALYST])
        response = self.client.get(reverse("accounts:home"))
        self.assertContains(response, 'class="welcome-panel"')
        self.assertContains(response, 'id="navigation-drawer"')
        self.assertNotContains(response, "Manage accounts")
        self.client.force_login(self.users[User.Role.ADMINISTRATOR])
        response = self.client.get(reverse("accounts:home"))
        self.assertContains(response, "Manage accounts")

    def test_theme_does_not_reintroduce_legacy_emerald_utilities(self):
        for template in (settings.PROJECT_ROOT / "templates").rglob("*.html"):
            with self.subTest(template=template.name):
                self.assertNotIn("emerald-", template.read_text(encoding="utf-8"))
        self.assertNotContains(self.client.get(reverse("accounts:login")), "emerald-")
