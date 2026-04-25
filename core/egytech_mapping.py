"""
Mappings from our internal enums (seniority, topic) to egytech.fyi enums (level, title).
Also contains free-text role aliases for the bot/dashboard role search.
"""

from typing import Optional

# Full set of egytech.fyi title enum values (from their OpenAPI spec).
EGYTECH_TITLES: frozenset[str] = frozenset({
    "backend", "frontend", "ai_automation", "crm", "data_analytics",
    "data_engineer", "data_scientist", "devops_sre_platform", "embedded",
    "engineering_manager", "executive", "fullstack", "hardware", "mobile",
    "product_manager", "product_owner", "testing", "research", "scrum",
    "security", "system_arch", "technical_support", "ui_ux",
})

# Full set of egytech.fyi level enum values.
EGYTECH_LEVELS: frozenset[str] = frozenset({
    "c_level", "director", "group_product_manager", "intern", "junior",
    "manager", "mid_level", "principal", "senior", "senior_manager",
    "senior_principal", "senior_staff", "staff", "team_lead", "vp",
})

# Our seniority enum -> egytech level enum.
SENIORITY_TO_LEVEL: dict[str, str] = {
    "intern":    "intern",
    "junior":    "junior",
    "mid":       "mid_level",
    "senior":    "senior",
    "lead":      "team_lead",
    "executive": "c_level",
}

# Our topic key -> egytech title enum.
# Topics not in this dict (gamedev, blockchain, erp, internships, general, egypt, saudi)
# have no clean mapping and produce no salary lookup.
TOPIC_TO_TITLE: dict[str, str] = {
    "backend":       "backend",
    "frontend":      "frontend",
    "fullstack":     "fullstack",
    "mobile":        "mobile",
    "devops":        "devops_sre_platform",
    "qa":            "testing",
    "cybersecurity": "security",
}

# Free-text aliases the user might type (in /salary or the dashboard search).
# Maps lowercased token -> egytech title.
_ROLE_ALIASES: dict[str, str] = {
    # backend
    "backend": "backend", "back-end": "backend", "back end": "backend",
    "python": "backend", "java": "backend", "node": "backend", "nodejs": "backend",
    "go": "backend", "golang": "backend", "rust": "backend", "ruby": "backend",
    "php": "backend", "django": "backend", "flask": "backend", "spring": "backend",
    "rails": "backend", "laravel": "backend", ".net": "backend", "c#": "backend",
    # frontend
    "frontend": "frontend", "front-end": "frontend", "front end": "frontend",
    "react": "frontend", "vue": "frontend", "angular": "frontend",
    "javascript": "frontend", "typescript": "frontend", "next.js": "frontend",
    "nextjs": "frontend", "svelte": "frontend",
    # fullstack
    "fullstack": "fullstack", "full-stack": "fullstack", "full stack": "fullstack",
    # mobile
    "mobile": "mobile", "ios": "mobile", "android": "mobile", "flutter": "mobile",
    "react native": "mobile", "swift": "mobile", "kotlin": "mobile",
    # devops / sre / platform
    "devops": "devops_sre_platform", "sre": "devops_sre_platform",
    "platform": "devops_sre_platform", "infra": "devops_sre_platform",
    "infrastructure": "devops_sre_platform", "cloud": "devops_sre_platform",
    "kubernetes": "devops_sre_platform", "k8s": "devops_sre_platform",
    # testing
    "qa": "testing", "test": "testing", "testing": "testing", "sdet": "testing",
    "automation": "testing",
    # security
    "security": "security", "cybersecurity": "security", "infosec": "security",
    "appsec": "security",
    # data
    "data engineer": "data_engineer", "data engineering": "data_engineer",
    "data scientist": "data_scientist", "data science": "data_scientist",
    "ml": "data_scientist", "machine learning": "data_scientist",
    "data analytics": "data_analytics", "analyst": "data_analytics",
    # embedded / hardware
    "embedded": "embedded", "firmware": "embedded", "iot": "embedded",
    "hardware": "hardware",
    # roles
    "ui": "ui_ux", "ux": "ui_ux", "ui/ux": "ui_ux", "designer": "ui_ux",
    "pm": "product_manager", "product manager": "product_manager",
    "po": "product_owner", "product owner": "product_owner",
    "em": "engineering_manager", "engineering manager": "engineering_manager",
    "scrum": "scrum", "scrum master": "scrum",
    "research": "research", "researcher": "research",
    "support": "technical_support", "technical support": "technical_support",
    "architect": "system_arch", "system architect": "system_arch",
    "ai": "ai_automation", "automation": "ai_automation",
    "crm": "crm",
}


def parse_role_query(text: Optional[str]) -> Optional[str]:
    """Resolve a free-text role query to an egytech title. Returns None on no match."""
    if not text:
        return None
    text = text.strip().lower()
    if not text:
        return None
    return _ROLE_ALIASES.get(text)
