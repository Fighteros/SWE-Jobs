"""
Salary extraction and normalization.
Parses salary strings into structured min/max/currency data.
Normalizes to yearly amounts.
"""

import re
from typing import Optional

# Currency detection patterns
_CURRENCY_MAP = {
    "$": "USD", "usd": "USD",
    "€": "EUR", "eur": "EUR", "euro": "EUR",
    "£": "GBP", "gbp": "GBP",
    "egp": "EGP",
    "sar": "SAR",
    "aed": "AED",
    "inr": "INR",
    "cad": "CAD",
    "aud": "AUD",
    "chf": "CHF",
    "pln": "PLN",
    "brl": "BRL",
    "sgd": "SGD",
}

# Period multipliers to normalize to yearly
_PERIOD_MULTIPLIERS = {
    "hour": 2080, "hr": 2080, "hourly": 2080,
    "month": 12, "monthly": 12, "mo": 12,
    "week": 52, "weekly": 52, "wk": 52,
    "year": 1, "yearly": 1, "annual": 1, "annually": 1, "yr": 1, "pa": 1,
}

# Regex to extract numbers (with optional k/K suffix)
_NUMBER_RE = re.compile(r'[\d,]+(?:\.\d+)?[kK]?')


def _parse_number(s: str) -> Optional[int]:
    """Parse a number string like '80,000', '80k', '80K' into an integer."""
    s = s.strip().replace(",", "")
    multiplier = 1
    if s.lower().endswith("k"):
        multiplier = 1000
        s = s[:-1]
    try:
        return int(float(s) * multiplier)
    except (ValueError, TypeError):
        return None


def _detect_currency(text: str) -> str:
    """Detect currency from text. Returns currency code or 'USD' as default."""
    text_lower = text.lower()
    for symbol, code in _CURRENCY_MAP.items():
        if symbol in text_lower:
            return code
    return "USD"


def _detect_period(text: str) -> int:
    """Detect pay period and return yearly multiplier."""
    text_lower = text.lower()
    for period, mult in _PERIOD_MULTIPLIERS.items():
        if period in text_lower:
            return mult
    return 1


def _infer_period_from_value(value: int) -> int:
    """Infer the pay period from the magnitude of the value."""
    if value < 500:
        return 2080  # Hourly
    elif value < 20000:
        return 12  # Monthly
    return 1  # Yearly


def parse_salary(raw: Optional[str]) -> Optional[dict]:
    """
    Parse a salary string into structured data.

    Returns: {"min": int, "max": int, "currency": str} or None if unparseable.
    All values normalized to yearly.
    """
    if not raw or not isinstance(raw, str):
        return None

    raw = raw.strip()
    if not raw:
        return None

    # Extract all numbers
    numbers = _NUMBER_RE.findall(raw)
    if not numbers:
        return None

    parsed = [_parse_number(n) for n in numbers]
    parsed = [n for n in parsed if n is not None and n > 0]

    if not parsed:
        return None

    currency = _detect_currency(raw)

    # Detect explicit period from text
    text_lower = raw.lower()
    period_mult = 1
    explicit_period = False
    for period, mult in _PERIOD_MULTIPLIERS.items():
        if period in text_lower:
            period_mult = mult
            explicit_period = True
            break

    if len(parsed) >= 2:
        sal_min, sal_max = parsed[0], parsed[1]
        if sal_min > sal_max:
            sal_min, sal_max = sal_max, sal_min
    else:
        sal_min = sal_max = parsed[0]

    # Infer period if not explicit
    if not explicit_period:
        period_mult = _infer_period_from_value(sal_min)

    sal_min = sal_min * period_mult
    sal_max = sal_max * period_mult

    return {"min": sal_min, "max": sal_max, "currency": currency}
