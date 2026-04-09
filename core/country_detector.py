"""
Country detection from job location strings.
Pattern-based, no external geocoding API needed.
"""

from typing import Optional
from core.geo import EGYPT_PATTERNS, SAUDI_PATTERNS

# Country pattern map: {ISO code: set of patterns}
_COUNTRY_PATTERNS: dict[str, set[str]] = {
    "EG": EGYPT_PATTERNS,
    "SA": SAUDI_PATTERNS,
    "US": {
        "united states", "usa", "u.s.a", "u.s.", "us-remote",
        "new york", "san francisco", "los angeles", "chicago", "seattle",
        "austin", "boston", "denver", "atlanta", "dallas", "houston",
        "miami", "philadelphia", "phoenix", "san jose", "san diego",
        "washington dc", "washington, dc",
    },
    "GB": {
        "united kingdom", "uk", "england", "scotland", "wales",
        "london", "manchester", "birmingham", "leeds", "bristol",
        "edinburgh", "glasgow", "cambridge", "oxford",
    },
    "DE": {
        "germany", "deutschland",
        "berlin", "munich", "frankfurt", "hamburg", "cologne",
        "stuttgart", "dusseldorf",
    },
    "CA": {
        "canada",
        "toronto", "vancouver", "montreal", "ottawa", "calgary",
    },
    "FR": {
        "france",
        "paris", "lyon", "marseille", "toulouse",
    },
    "NL": {
        "netherlands", "holland",
        "amsterdam", "rotterdam", "the hague", "utrecht",
    },
    "IN": {
        "india",
        "bangalore", "bengaluru", "mumbai", "delhi", "hyderabad",
        "pune", "chennai", "kolkata", "noida", "gurgaon", "gurugram",
    },
    "AE": {
        "uae", "united arab emirates",
        "dubai", "abu dhabi", "sharjah",
    },
    "AU": {
        "australia",
        "sydney", "melbourne", "brisbane", "perth",
    },
    "SG": {"singapore"},
    "IE": {"ireland", "dublin"},
    "ES": {"spain", "madrid", "barcelona"},
    "IT": {"italy", "milan", "rome"},
    "PT": {"portugal", "lisbon", "porto"},
    "PL": {"poland", "warsaw", "krakow", "wroclaw"},
    "SE": {"sweden", "stockholm", "gothenburg"},
    "CH": {"switzerland", "zurich", "geneva", "basel"},
    "JP": {"japan", "tokyo", "osaka"},
    "KR": {"south korea", "korea", "seoul"},
    "BR": {"brazil", "sao paulo", "rio de janeiro"},
    "IL": {"israel", "tel aviv", "jerusalem"},
    "NG": {"nigeria", "lagos", "abuja"},
    "KE": {"kenya", "nairobi"},
    "ZA": {"south africa", "cape town", "johannesburg"},
    "TR": {"turkey", "turkiye", "istanbul", "ankara"},
    "RO": {"romania", "bucharest"},
    "UA": {"ukraine", "kyiv"},
    "AR": {"argentina", "buenos aires"},
    "MX": {"mexico", "mexico city", "guadalajara"},
    "CO": {"colombia", "bogota", "medellin"},
}


def detect_country(location: Optional[str]) -> str:
    """
    Detect country ISO code from a location string.

    Returns 2-letter ISO code (e.g. 'US', 'EG') or empty string if unknown.
    """
    if not location:
        return ""

    loc_lower = location.lower().strip()

    if not loc_lower:
        return ""

    for iso_code, patterns in _COUNTRY_PATTERNS.items():
        for pattern in patterns:
            if pattern in loc_lower:
                return iso_code

    return ""
