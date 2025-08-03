"""Template tags for Freight."""

from django import template

register = template.Library()


@register.filter
def power10(value, k=0):
    """converts the value to a power of 10 representation"""
    try:
        return float(value) / (10 ** int(k))
    except (ValueError, TypeError):
        return None


@register.filter
def formatnumber(value, precision=1):
    """return a formatted number with thousands separators"""
    try:
        return f"{value:,.{precision}f}"
    except (ValueError, TypeError):
        return None
