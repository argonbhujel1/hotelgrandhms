from decimal import Decimal, ROUND_HALF_UP


TWOPLACES = Decimal("0.01")


def money(value) -> Decimal:
    """Convert to Decimal with 2 decimal places."""
    if value is None:
        return Decimal("0.00")
    return Decimal(str(value)).quantize(TWOPLACES, rounding=ROUND_HALF_UP)


def calc_vat_inclusive(inclusive_total, vat_rate=Decimal("13")):
    """
    VAT inclusive pricing.
    Customer pays inclusive_total.
    Before VAT = inclusive / (1 + rate/100)
    VAT = inclusive - before
    Returns (before_vat, vat_amount, final_total) all Decimal.
    """
    inclusive = money(inclusive_total)
    rate = money(vat_rate)
    divisor = Decimal("1") + (rate / Decimal("100"))
    before = (inclusive / divisor).quantize(TWOPLACES, rounding=ROUND_HALF_UP)
    vat = (inclusive - before).quantize(TWOPLACES, rounding=ROUND_HALF_UP)
    return before, vat, inclusive


def line_total(unit_price, quantity) -> Decimal:
    return money(unit_price) * int(quantity)
