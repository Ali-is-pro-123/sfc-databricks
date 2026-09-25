"""Business administration separate from the privileged user console."""

from django.contrib import admin
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ValidationError

from . import models


class ManagementLoginForm(AuthenticationForm):
    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if not user.can_manage_accounts:
            raise ValidationError("An administrator account is required.", code="invalid_login")


class ManagementSite(admin.AdminSite):
    login_form = ManagementLoginForm
    site_header = "DineIQ Management"
    site_title = "DineIQ Management"
    index_title = "Restaurant records"
    site_url = "/locations/"

    def has_permission(self, request):
        return request.user.is_authenticated and request.user.can_manage_accounts


management_site = ManagementSite(name="management")


class DomainAdmin(admin.ModelAdmin):
    list_per_page = 50
    show_full_result_count = False
    list_display = ("code",)
    search_fields = ("code",)
    readonly_fields = ("created_at",)

    def has_module_permission(self, request):
        return management_site.has_permission(request)

    def has_view_permission(self, request, obj=None):
        return self.has_module_permission(request)

    def has_add_permission(self, request):
        return self.has_module_permission(request)

    def has_change_permission(self, request, obj=None):
        return self.has_module_permission(request)

    def has_delete_permission(self, request, obj=None):
        # Preserve historical records; use status/availability flags to retire them.
        return False


@admin.register(models.Restaurant, site=management_site)
class RestaurantAdmin(DomainAdmin):
    list_display = ("code", "name", "city", "is_active")
    search_fields = ("code", "name", "city")
    list_filter = ("is_active", "city")


@admin.register(models.MenuCategory, site=management_site)
class CategoryAdmin(DomainAdmin):
    list_display = ("code", "name")
    search_fields = ("code", "name")


@admin.register(models.MenuItem, site=management_site)
class MenuItemAdmin(DomainAdmin):
    list_display = ("code", "name", "category", "is_available")
    search_fields = ("code", "name")
    list_filter = ("category", "is_available")
    autocomplete_fields = ("category",)


@admin.register(models.PricingHistory, site=management_site)
class PricingAdmin(DomainAdmin):
    list_display = ("code", "restaurant", "item", "effective_at", "unit_price", "unit_cost")
    autocomplete_fields = ("restaurant", "item")
    date_hierarchy = "effective_at"


@admin.register(models.Order, site=management_site)
class OrderAdmin(DomainAdmin):
    list_display = ("code", "restaurant", "ordered_at", "status")
    autocomplete_fields = ("restaurant", "customer", "channel", "promotion")
    list_filter = ("status", "channel")
    date_hierarchy = "ordered_at"


@admin.register(models.OrderItem, site=management_site)
class OrderItemAdmin(DomainAdmin):
    list_display = ("code", "order", "line_number", "item", "quantity", "unit_price")
    autocomplete_fields = ("order", "item", "promotion")


@admin.register(models.Promotion, site=management_site)
class PromotionAdmin(DomainAdmin):
    list_display = ("code", "name", "starts_at", "ends_at", "discount_percent")
    search_fields = ("code", "name", "coupon_code")
    autocomplete_fields = ("items",)


@admin.register(models.Rating, site=management_site)
class RatingAdmin(DomainAdmin):
    list_display = ("code", "order_item", "score", "rated_at")
    autocomplete_fields = ("order_item",)
    list_filter = ("score",)


@admin.register(models.Inventory, site=management_site)
class InventoryAdmin(DomainAdmin):
    list_display = ("code", "restaurant", "item", "date", "closing_quantity")
    autocomplete_fields = ("restaurant", "item")
    date_hierarchy = "date"


@admin.register(models.Wastage, site=management_site)
class WastageAdmin(DomainAdmin):
    list_display = ("code", "restaurant", "item", "recorded_at", "wasted_quantity", "wastage_cost")
    autocomplete_fields = ("restaurant", "item")
    date_hierarchy = "recorded_at"


@admin.register(models.OrderingChannel, site=management_site)
class ChannelAdmin(DomainAdmin):
    list_display = ("code", "name")
    search_fields = ("code", "name")


management_site.register(models.Customer, DomainAdmin)


@admin.register(models.LocationAccess, site=management_site)
class AccessAdmin(DomainAdmin):
    list_display = ("user", "restaurant")
    search_fields = ("user__username", "restaurant__code")
    readonly_fields = ()
    autocomplete_fields = ("restaurant",)

    def has_delete_permission(self, request, obj=None):
        return self.has_module_permission(request)
