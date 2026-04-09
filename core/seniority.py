"""
Seniority level detection from job titles.
"""

import re
from typing import Optional

# Ordered by priority: higher priority patterns are checked first.
# Patterns use word boundaries to avoid false matches (e.g. "internal" matching "intern").
_SENIORITY_PATTERNS = [
    ("executive", [
        r"\bcto\b", r"\bvp\b", r"\bvice president\b",
        r"\bhead of\b", r"\bdirector\b",
        r"\bchief\b",
    ]),
    ("lead", [
        r"\blead\b", r"\bprincipal\b", r"\bstaff\b",
        r"\barchitect\b",
    ]),
    ("senior", [
        r"\bsenior\b", r"\bsr\.?\b", r"\bexperienced\b",
    ]),
    ("intern", [
        r"\bintern\b", r"\binternship\b", r"\btrainee\b",
        r"\bco-op\b", r"\bcoop\b",
    ]),
    ("junior", [
        r"\bjunior\b", r"\bjr\.?\b", r"\bentry[\s-]?level\b",
        r"\bfresh\s*grad", r"\bassociate\b",
    ]),
    ("mid", [
        r"\bmid[\s-]?level\b", r"\bintermediate\b",
    ]),
]


def detect_seniority(title: Optional[str]) -> str:
    """
    Detect seniority level from a job title.

    Returns one of: 'intern', 'junior', 'mid', 'senior', 'lead', 'executive'.
    Defaults to 'mid' if no pattern matches.
    """
    if not title:
        return "mid"

    title_lower = title.lower()

    for level, patterns in _SENIORITY_PATTERNS:
        for pattern in patterns:
            if re.search(pattern, title_lower):
                return level

    return "mid"
