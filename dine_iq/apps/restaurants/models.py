"""Validated restaurant records used by the application and analytical imports."""

from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q


def nonnegative(field):
    return Q(**{f"{field}__gte": 0})


class Record(models.Model):
    code = models.CharField(max_length=40, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        # Imports using bulk_create must validate rows in their ingestion pipeline.
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.code} - {self.name}" if hasattr(self, "name") else self.code


class Restaurant(Record):
    name = models.CharField(max_length=150)
    city = models.CharField(max_length=100)
    address = models.TextField(blank=True)
    timezone = models.CharField(max_length=64, default="Asia/Karachi")
    is_active = models.BooleanField(default=True)

    def clean(self):
        super().clean()
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValidationError({"timezone": "Enter a valid IANA time zone."})


class LocationAccess(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE, related_name="access_grants")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "restaurant"], name="unique_location_access")]
        verbose_name_plural = "Location access grants"

    def __str__(self):
        return f"{self.user} / {self.restaurant}"


class MenuCategory(Record):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)

    class Meta:
        verbose_name_plural = "Menu categories"


class MenuItem(Record):
    category = models.ForeignKey(MenuCategory, on_delete=models.PROTECT, related_name="items")
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    is_available = models.BooleanField(default=True)


class PricingHistory(Record):
    restaurant = models.ForeignKey(Restaurant, on_delete=models.PROTECT)
    item = models.ForeignKey(MenuItem, on_delete=models.PROTECT, related_name="price_history")
    effective_at = models.DateTimeField()
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        verbose_name_plural = "Pricing history"
        constraints = [
            models.UniqueConstraint(fields=["restaurant", "item", "effective_at"], name="unique_price_event"),
            models.CheckConstraint(condition=nonnegative("unit_price") & nonnegative("unit_cost"), name="price_cost_nonnegative"),
        ]


class Customer(Record):
    joined_on = models.DateField()
    # This identifier is pseudonymous; names, email addresses and phone numbers are omitted.
    cohort = models.CharField(max_length=64, blank=True)


class OrderingChannel(Record):
    name = models.CharField(max_length=100, unique=True)


class Promotion(Record):
    name = models.CharField(max_length=150)
    coupon_code = models.CharField(max_length=50, blank=True)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    discount_percent = models.DecimalField(max_digits=5, decimal_places=2)
    items = models.ManyToManyField(MenuItem, blank=True, related_name="promotions")

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(ends_at__gt=F("starts_at")), name="promotion_valid_dates"),
            models.CheckConstraint(condition=nonnegative("discount_percent") & Q(discount_percent__lte=100), name="promotion_valid_discount"),
        ]


class Order(Record):
    class Status(models.TextChoices):
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    restaurant = models.ForeignKey(Restaurant, on_delete=models.PROTECT, related_name="orders")
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, null=True, blank=True, related_name="orders")
    channel = models.ForeignKey(OrderingChannel, on_delete=models.PROTECT)
    promotion = models.ForeignKey(Promotion, on_delete=models.PROTECT, null=True, blank=True)
    ordered_at = models.DateTimeField()
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.COMPLETED)

    class Meta:
        indexes = [models.Index(fields=["restaurant", "ordered_at"]), models.Index(fields=["status", "ordered_at"])]
        constraints = [models.CheckConstraint(condition=Q(status__in=["completed", "cancelled"]), name="valid_order_status")]

    def clean(self):
        super().clean()
        if self.promotion_id and self.ordered_at:
            if not self.promotion.starts_at <= self.ordered_at < self.promotion.ends_at:
                raise ValidationError({"promotion": "The order must fall within the campaign period."})


class OrderItem(Record):
    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name="lines")
    line_number = models.PositiveIntegerField()
    item = models.ForeignKey(MenuItem, on_delete=models.PROTECT)
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2)
    discount_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    promotion = models.ForeignKey(Promotion, on_delete=models.PROTECT, null=True, blank=True,
                                  help_text="Campaign responsible for this line's discount, if any.")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["order", "line_number"], name="unique_order_line"),
            models.CheckConstraint(condition=Q(quantity__gt=0) & Q(line_number__gt=0), name="positive_order_line_quantity"),
            models.CheckConstraint(condition=nonnegative("unit_price") & nonnegative("unit_cost") & nonnegative("discount_amount"), name="line_amounts_nonnegative"),
            models.CheckConstraint(condition=Q(discount_amount__lte=F("quantity") * F("unit_price")), name="discount_not_above_gross"),
        ]

    @property
    def revenue(self):
        return self.quantity * self.unit_price - self.discount_amount

    def clean(self):
        super().clean()
        if self.promotion_id and self.order_id and self.item_id:
            if self.promotion_id != self.order.promotion_id:
                raise ValidationError({"promotion": "Line campaign must match the order campaign."})
            if not self.promotion.items.filter(pk=self.item_id).exists():
                raise ValidationError({"promotion": "This item is not eligible for the campaign."})

    @property
    def contribution_margin(self):
        return self.revenue - self.quantity * self.unit_cost


class Rating(Record):
    order_item = models.OneToOneField(OrderItem, on_delete=models.PROTECT, related_name="rating")
    score = models.PositiveSmallIntegerField()
    rated_at = models.DateTimeField()

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(score__gte=1, score__lte=5), name="rating_between_one_five")]

    def clean(self):
        super().clean()
        if self.order_item_id and self.rated_at:
            order = self.order_item.order
            if order.status != Order.Status.COMPLETED or self.rated_at < order.ordered_at:
                raise ValidationError("Ratings require a completed purchase and cannot predate it.")


class Inventory(Record):
    restaurant = models.ForeignKey(Restaurant, on_delete=models.PROTECT)
    item = models.ForeignKey(MenuItem, on_delete=models.PROTECT)
    date = models.DateField()
    opening_quantity = models.DecimalField(max_digits=12, decimal_places=3)
    replenished_quantity = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    consumed_quantity = models.DecimalField(max_digits=12, decimal_places=3, default=0)

    class Meta:
        verbose_name_plural = "Inventory snapshots"
        constraints = [
            models.UniqueConstraint(fields=["restaurant", "item", "date"], name="unique_inventory_snapshot"),
            models.CheckConstraint(condition=nonnegative("opening_quantity") & nonnegative("replenished_quantity") & nonnegative("consumed_quantity"), name="inventory_nonnegative"),
            models.CheckConstraint(condition=Q(consumed_quantity__lte=F("opening_quantity") + F("replenished_quantity")), name="inventory_within_stock"),
        ]

    @property
    def closing_quantity(self):
        return self.opening_quantity + self.replenished_quantity - self.consumed_quantity


class Wastage(Record):
    restaurant = models.ForeignKey(Restaurant, on_delete=models.PROTECT)
    item = models.ForeignKey(MenuItem, on_delete=models.PROTECT)
    recorded_at = models.DateTimeField()
    prepared_quantity = models.DecimalField(max_digits=12, decimal_places=3)
    wasted_quantity = models.DecimalField(max_digits=12, decimal_places=3)
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2)
    reason = models.CharField(max_length=255)

    class Meta:
        verbose_name_plural = "Wastage records"
        indexes = [models.Index(fields=["restaurant", "recorded_at"])]
        constraints = [
            models.CheckConstraint(condition=nonnegative("prepared_quantity") & nonnegative("wasted_quantity") & nonnegative("unit_cost"), name="wastage_nonnegative"),
            models.CheckConstraint(condition=Q(wasted_quantity__lte=F("prepared_quantity")), name="wastage_within_prepared"),
        ]

    @property
    def wastage_cost(self):
        return self.wasted_quantity * self.unit_cost
