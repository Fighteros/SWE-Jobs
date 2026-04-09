"""
Keyword scoring weights and keyword lists for job filtering.
"""

# ─── Scoring weights ─────────────────────────────────────────
SCORE_EXACT_WORD = 10   # Whole word match in title (regex \b)
SCORE_TAG_MATCH = 8     # Exact match in tags array
SCORE_PARTIAL = 3       # Substring match (no word boundary)
SCORE_EXCLUDE = -20     # Exclude keyword found (instant reject)
SCORE_THRESHOLD = 10    # Minimum score to pass

# ─── Include Keywords ────────────────────────────────────────
# Job MUST contain at least one of these (case-insensitive, checked in title + tags)
INCLUDE_KEYWORDS = [
    # Software Engineering
    "software engineer", "software developer", "software development",
    "swe", "sde",
    # Backend
    "backend", "back-end", "back end",
    "server-side", "server side",
    "api developer", "api engineer",
    # Frontend
    "frontend", "front-end", "front end",
    "ui developer", "ui engineer",
    # Full-Stack
    "full-stack", "full stack", "fullstack",
    # DevOps / SRE / Cloud / Infra
    "devops", "dev ops", "dev-ops",
    "sre", "site reliability",
    "cloud engineer", "cloud developer", "cloud architect",
    "infrastructure engineer", "platform engineer",
    "kubernetes", "docker", "terraform",
    "aws engineer", "azure engineer", "gcp engineer",
    # QA / Testing
    "qa engineer", "qa developer", "quality assurance",
    "test engineer", "sdet", "software tester",
    "automation engineer", "test automation",
    "qa analyst", "qa lead", "qa manager",
    # Mobile — expanded
    "mobile developer", "mobile engineer", "mobile application",
    "ios developer", "ios engineer",
    "android developer", "android engineer",
    "flutter developer", "flutter engineer", "flutter",
    "react native developer", "react native engineer", "react native",
    "swift developer", "kotlin developer",
    "mobile app developer", "app developer",
    # Web Development
    "web developer", "web engineer", "webmaster",
    # AI / ML / Data Science
    "machine learning", "ml engineer", "ml developer",
    "ai engineer", "ai developer", "artificial intelligence",
    "deep learning", "nlp engineer", "computer vision",
    "data scientist", "data science",
    "data analyst", "data analytics",
    "data engineer", "etl developer", "data pipeline",
    "big data", "hadoop", "spark engineer",
    # Cybersecurity
    "security engineer", "appsec", "application security",
    "cybersecurity", "cyber security", "infosec",
    "penetration tester", "pen tester", "security analyst",
    "soc analyst", "security architect",
    # Database
    "database administrator", "dba",
    "database developer", "database engineer",
    "sql developer", "postgresql", "mongodb",
    # Blockchain / Web3
    "blockchain developer", "blockchain engineer",
    "smart contract", "solidity developer",
    "web3 developer", "web3 engineer",
    "crypto developer",
    # Game Development
    "game developer", "game engineer", "game programmer",
    "unity developer", "unreal developer",
    "game designer",  # programming-focused game design
    # Embedded / IoT
    "embedded developer", "embedded engineer", "embedded software",
    "iot developer", "iot engineer",
    "firmware developer", "firmware engineer",
    # Systems / Low-level
    "systems engineer", "systems developer",
    "systems programmer", "kernel developer",
    "linux engineer", "os developer",
    # ERP / CRM
    "salesforce developer", "sap developer", "sap engineer",
    "erp developer", "crm developer",
    "dynamics developer", "odoo developer",
    # Networking
    "network engineer", "network administrator",
    "network architect",
    # Programming Languages (as job titles)
    "python developer", "python engineer",
    "java developer", "java engineer",
    "javascript developer", "js developer",
    "typescript developer", "ts developer",
    "golang developer", "go developer", "go engineer",
    "rust developer", "rust engineer",
    "ruby developer", "ruby engineer", "rails developer",
    "php developer", "php engineer",
    "c# developer", ".net developer", "dotnet developer",
    "c++ developer", "cpp developer",
    "scala developer", "elixir developer",
    "perl developer", "r developer",
    # Frameworks (as job titles)
    "node.js developer", "nodejs developer", "node developer",
    "react developer", "react engineer", "next.js developer",
    "angular developer", "vue developer", "vue.js developer",
    "django developer", "flask developer", "fastapi",
    "spring developer", "spring boot",
    "laravel developer", "symfony developer",
    "express.js developer",
    # CMS / WordPress
    "wordpress developer", "shopify developer",
    "drupal developer", "magento developer",
    # Technical Leadership
    "tech lead", "technical lead", "engineering manager",
    "cto", "vp engineering", "head of engineering",
    "principal engineer", "staff engineer", "architect",
    # Teaching / Tutoring
    "coding instructor", "programming instructor",
    "coding tutor", "programming tutor",
    "coding teacher", "programming teacher",
    "bootcamp instructor", "technical instructor",
    "computer science instructor", "cs instructor",
    "technical trainer", "coding mentor",
    # ERP / CRM / Accounting
    "erp developer", "erp consultant", "erp engineer",
    "odoo developer", "odoo engineer", "odoo consultant", "odoo",
    "sap developer", "sap consultant", "sap engineer",
    "sap abap", "sap fiori", "sap hana", "sap basis",
    "salesforce developer", "salesforce engineer", "salesforce admin",
    "dynamics developer", "dynamics 365", "dynamics consultant",
    "oracle developer", "oracle ebs", "oracle apps", "oracle dba",
    "netsuite developer", "netsuite consultant",
    "quickbooks developer",
    "crm developer", "crm engineer",
    "accounting software", "financial software",
    # Internships / Entry Level
    "intern", "internship", "trainee",
    "graduate program", "training program",
    "co-op", "apprentice", "apprenticeship",
    "working student", "student developer",
    # General (broad catch — filtered by EXCLUDE)
    "programmer", "developer", "engineer",
]

# ─── Exclude Keywords ────────────────────────────────────────
# Job is EXCLUDED if it contains any of these (case-insensitive)
EXCLUDE_KEYWORDS = [
    # Non-programming roles
    "graphic design", "ui/ux design", "ux design", "ux researcher",
    "product design", "visual design", "brand design", "interior design",
    "marketing", "sales", "account manager", "account executive",
    "recruiter", "talent acquisition", "hr manager", "human resources",
    "customer support", "customer service", "customer success",
    "content writer", "copywriter",
    "project manager", "program manager", "scrum master",
    "product manager", "product owner",
    "business analyst", "business development",
    "financial analyst", "accountant", "bookkeeper",
    "office manager", "administrative",
    "data entry", "virtual assistant",
    "social media manager", "community manager",
    "supply chain", "logistics",
    # Hardware / Non-software engineering
    "mechanical engineer", "electrical engineer", "civil engineer",
    "chemical engineer", "structural engineer",
    "hardware engineer", "pcb",
    # Medical / Other
    "medical coder", "billing coder", "clinical",
    "nurse", "physician", "pharmacist",
    "dental", "veterinary",
]
