from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from .access import visible_restaurants
from .models import (
    Customer, Inventory, LocationAccess, MenuCategory, MenuItem, Order,
    OrderingChannel, OrderItem, PricingHistory, Promotion, Rating, Restaurant, Wastage,
)


class DomainTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.now = timezone.now()
        cls.a = Restaurant.objects.create(code="R1", name="Central", city="Karachi")
        cls.b = Restaurant.objects.create(code="R2", name="North", city="Lahore")
        cls.category = MenuCategory.objects.create(code="C1", name="Meals")
        cls.item = MenuItem.objects.create(code="M1", name="Rice Bowl", category=cls.category)
        cls.channel = OrderingChannel.objects.create(code="CH1", name="Dine-in")
        cls.customer = Customer.objects.create(code="CU1", joined_on=cls.now.date())
        cls.order = Order.objects.create(code="O1", restaurant=cls.a, customer=cls.customer,
                                       channel=cls.channel, ordered_at=cls.now)
        cls.line = OrderItem.objects.create(code="L1", order=cls.order, line_number=1,
                                          item=cls.item, quantity=2, unit_price="100.00",
                                          unit_cost="120.00", discount_amount="10.00")
        cls.users = {role: User.objects.create_user(username=role, role=role) for role in User.Role.values}

    def test_decimal_loss_making_line_is_valid(self):
        self.line.refresh_from_db()
        self.assertEqual(self.line.revenue, Decimal("190.00"))
        self.assertEqual(self.line.contribution_margin, Decimal("-50.00"))

    def test_price_changes_do_not_rewrite_sale_snapshots(self):
        PricingHistory.objects.create(code="P1", restaurant=self.a, item=self.item,
                                      effective_at=self.now, unit_price=200, unit_cost=150)
        self.line.refresh_from_db()
        self.assertEqual(self.line.unit_price, Decimal("100.00"))

    def test_line_validation(self):
        for values in ({"quantity": 0}, {"unit_price": -1}, {"unit_cost": -1},
                       {"discount_amount": -1}, {"discount_amount": 201}, {"line_number": 0}):
            with self.subTest(values=values):
                self.line.refresh_from_db()
                for key, value in values.items():
                    setattr(self.line, key, value)
                with self.assertRaises(ValidationError):
                    self.line.save()

    def test_database_constraints_cannot_be_bypassed_by_bulk_updates(self):
        for values in ({"quantity": 0}, {"discount_amount": 201}, {"unit_cost": -1}):
            with self.subTest(values=values), self.assertRaises(IntegrityError), transaction.atomic():
                OrderItem.objects.filter(pk=self.line.pk).update(**values)

    def test_duplicate_line_and_duplicate_access_rejected(self):
        with self.assertRaises(ValidationError):
            OrderItem.objects.create(code="L2", order=self.order, line_number=1, item=self.item,
                                     quantity=1, unit_price=100, unit_cost=20)
        user = self.users[User.Role.RESTAURANT_MANAGER]
        LocationAccess.objects.create(user=user, restaurant=self.a)
        with self.assertRaises(IntegrityError), transaction.atomic():
            LocationAccess.objects.create(user=user, restaurant=self.a)

    def test_rating_validation(self):
        for score, date in ((0, self.now), (6, self.now), (5, self.now - timedelta(seconds=1))):
            with self.subTest(score=score, date=date), self.assertRaises(ValidationError):
                Rating.objects.create(code="RT1", order_item=self.line, score=score, rated_at=date)
        self.order.status = Order.Status.CANCELLED
        self.order.save()
        with self.assertRaises(ValidationError):
            Rating.objects.create(code="RT1", order_item=self.line, score=5, rated_at=self.now)

    def test_valid_rating_and_anonymous_cancelled_order(self):
        Rating.objects.create(code="RT1", order_item=self.line, score=5, rated_at=self.now)
        order = Order.objects.create(code="O2", restaurant=self.a, channel=self.channel,
                                     ordered_at=self.now, status=Order.Status.CANCELLED)
        self.assertIsNone(order.customer)

    def test_promotion_date_and_percent_rules(self):
        for end, percent in ((self.now, 20), (self.now + timedelta(days=1), 101),
                             (self.now + timedelta(days=1), -1)):
            with self.subTest(end=end, percent=percent), self.assertRaises(ValidationError):
                Promotion.objects.create(code="PR1", name="Campaign", starts_at=self.now,
                                         ends_at=end, discount_percent=percent)
        campaign = Promotion.objects.create(code="PR1", name="Campaign", starts_at=self.now,
                                            ends_at=self.now + timedelta(days=1), discount_percent=10)
        self.order.promotion = campaign
        self.order.save()
        self.order.ordered_at = campaign.ends_at
        with self.assertRaises(ValidationError):
            self.order.save()

    def test_inventory_and_wastage_bounds(self):
        stock = Inventory.objects.create(code="I1", restaurant=self.a, item=self.item,
                                         date=self.now.date(), opening_quantity=10,
                                         replenished_quantity=5, consumed_quantity=12)
        self.assertEqual(stock.closing_quantity, 3)
        stock.consumed_quantity = 16
        with self.assertRaises(ValidationError):
            stock.save()
        waste = Wastage.objects.create(code="W1", restaurant=self.a, item=self.item,
                                       recorded_at=self.now, prepared_quantity=10,
                                       wasted_quantity=2, unit_cost=30, reason="Overproduction")
        self.assertEqual(waste.wastage_cost, Decimal("60"))
        waste.wasted_quantity = 11
        with self.assertRaises(ValidationError):
            waste.save()

    def test_unknown_timezone_rejected(self):
        self.a.timezone = "Unknown/Place"
        with self.assertRaises(ValidationError):
            self.a.save()

    def test_referenced_menu_cannot_be_deleted(self):
        with self.assertRaises(ProtectedError):
            self.item.delete()

    def test_scoping_for_all_roles(self):
        self.assertFalse(visible_restaurants(AnonymousUser()).exists())
        for role, user in self.users.items():
            with self.subTest(role=role):
                global_access = role in (User.Role.ADMINISTRATOR, User.Role.ANALYST)
                self.assertEqual(visible_restaurants(user).count(), 2 if global_access else 0)
                LocationAccess.objects.create(user=user, restaurant=self.a)
                self.assertEqual(visible_restaurants(user).count(), 2 if global_access else 1)
                self.client.force_login(user)
                self.assertEqual(self.client.get(reverse("restaurants:detail", args=[self.a.pk])).status_code, 200)
                self.assertEqual(self.client.get(reverse("restaurants:detail", args=[self.b.pk])).status_code,
                                 200 if global_access else 404)

    def test_grant_revocation_takes_effect_immediately(self):
        user = self.users[User.Role.REGIONAL_MANAGER]
        grant = LocationAccess.objects.create(user=user, restaurant=self.a)
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse("restaurants:detail", args=[self.a.pk])).status_code, 200)
        grant.delete()
        self.assertEqual(self.client.get(reverse("restaurants:detail", args=[self.a.pk])).status_code, 404)
        user.is_active = False
        self.assertFalse(visible_restaurants(user).exists())

    def test_current_prices_exclude_old_future_and_other_location(self):
        for code, offset, location, price in (("P1", -2, self.a, 100), ("P2", -1, self.a, 200),
                                              ("P3", 1, self.a, 300), ("P4", -1, self.b, 400)):
            PricingHistory.objects.create(code=code, item=self.item, restaurant=location,
                                          effective_at=self.now + timedelta(days=offset),
                                          unit_price=price, unit_cost=80)
        self.client.force_login(self.users[User.Role.ANALYST])
        response = self.client.get(reverse("restaurants:detail", args=[self.a.pk]))
        self.assertEqual([p.code for p in response.context["page_obj"]], ["P2"])
        with self.assertRaises(ValidationError):
            PricingHistory.objects.create(code="P5", item=self.item, restaurant=self.a,
                                          effective_at=self.now - timedelta(days=1), unit_price=300, unit_cost=80)

    def test_management_restricted_and_administrator_can_create(self):
        for role, user in self.users.items():
            self.client.force_login(user)
            expected = 200 if role == User.Role.ADMINISTRATOR else 302
            self.assertEqual(self.client.get(reverse("management:index")).status_code, expected)
            self.assertEqual(self.client.get(reverse("management:restaurants_restaurant_add")).status_code, expected)
        self.client.force_login(self.users[User.Role.ADMINISTRATOR])
        response = self.client.post(reverse("management:restaurants_restaurant_add"), {
            "code": "R3", "name": "South", "city": "Karachi", "timezone": "Asia/Karachi",
            "is_active": "on", "_save": "Save",
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Restaurant.objects.filter(code="R3").exists())

    def test_administrator_can_manage_grants_without_user_admin_access(self):
        self.client.force_login(self.users[User.Role.ADMINISTRATOR])
        url = reverse("management:restaurants_locationaccess_add")
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.post(url, {
            "user": self.users[User.Role.REGIONAL_MANAGER].pk, "restaurant": self.a.pk,
            "_save": "Save",
        }).status_code, 302)
        self.assertEqual(self.client.get(reverse("admin:accounts_user_changelist")).status_code, 302)

    def test_domain_admin_pages_render(self):
        self.client.force_login(self.users[User.Role.ADMINISTRATOR])
        names = ("restaurant", "menucategory", "menuitem", "pricinghistory", "customer",
                 "orderingchannel", "promotion", "order", "orderitem", "rating", "inventory", "wastage")
        for name in names:
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse(f"management:restaurants_{name}_add")).status_code, 200)
                self.assertEqual(self.client.get(reverse(f"management:restaurants_{name}_changelist")).status_code, 200)

    def test_business_administrator_can_login_directly_without_staff_flag(self):
        user = self.users[User.Role.ADMINISTRATOR]
        user.set_password("Domain-test-Strong-password-75!")
        user.save()
        self.assertFalse(user.is_staff)
        response = self.client.post(reverse("management:login"), {
            "username": user.username, "password": "Domain-test-Strong-password-75!",
            "next": reverse("management:index"),
        })
        self.assertRedirects(response, reverse("management:index"))

    def test_manager_cannot_login_to_management(self):
        user = self.users[User.Role.RESTAURANT_MANAGER]
        user.set_password("Domain-test-Strong-password-75!")
        user.save()
        response = self.client.post(reverse("management:login"), {
            "username": user.username, "password": "Domain-test-Strong-password-75!",
        })
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_line_campaign_must_match_order_and_applicable_item(self):
        campaign = Promotion.objects.create(code="CP1", name="Offer", starts_at=self.now,
                                            ends_at=self.now + timedelta(days=1), discount_percent=10)
        self.line.promotion = campaign
        with self.assertRaises(ValidationError):
            self.line.save()
        self.order.promotion = campaign
        self.order.save()
        with self.assertRaises(ValidationError):
            self.line.save()
        campaign.items.add(self.item)
        self.line.save()
