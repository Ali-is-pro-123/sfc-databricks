"""Compact display helpers for verified dashboard values."""

from decimal import Decimal, InvalidOperation

from django import template


register = template.Library()


@register.filter
def compact_number(value):
    """Shorten large values without changing the underlying analytical measure."""
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return "—"
    magnitude = abs(number)
    for threshold, suffix in ((Decimal("1000000000"), "B"),
                              (Decimal("1000000"), "M"),
                              (Decimal("1000"), "K")):
        if magnitude >= threshold:
            return f"{number / threshold:,.1f}{suffix}"
    return f"{number:,.0f}"
