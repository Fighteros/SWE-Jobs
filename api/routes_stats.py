"""Statistics, salary insights, and trend endpoints."""

import logging
from fastapi import APIRouter, Query, Request
from typing import Optional
from api.middleware import limiter
from core import db
from core.egytech import get_stats
from core.egytech_mapping import parse_role_query, SENIORITY_TO_LEVEL

log = logging.getLogger(__name__)

router = APIRouter()


@router.get("/summary")
@limiter.limit("30/minute")
async def stats_summary(request: Request):
    """Aggregated stats for the dashboard home page."""
    today = db._fetchone(
        "SELECT COUNT(*) as count FROM jobs WHERE created_at > now() - make_interval(days := 1)"
    )
    week = db._fetchone(
        "SELECT COUNT(*) as count FROM jobs WHERE created_at > now() - make_interval(days := 7)"
    )
    total = db._fetchone("SELECT COUNT(*) as count FROM jobs")

    by_source = db._fetchall(
        """SELECT source, COUNT(*) as count FROM jobs
           WHERE created_at > now() - make_interval(days := 7)
           GROUP BY source ORDER BY count DESC"""
    )

    by_topic = db._fetchall(
        """SELECT unnest(topics) as topic, COUNT(*) as count FROM jobs
           WHERE created_at > now() - make_interval(days := 7)
           GROUP BY topic ORDER BY count DESC"""
    )

    top_companies = db._fetchall(
        """SELECT company, COUNT(*) as count FROM jobs
           WHERE created_at > now() - make_interval(days := 7)
             AND company != ''
           GROUP BY company ORDER BY count DESC LIMIT 10"""
    )

    return {
        "jobs_today": today["count"] if today else 0,
        "jobs_week": week["count"] if week else 0,
        "jobs_total": total["count"] if total else 0,
        "by_source": by_source,
        "by_topic": by_topic,
        "top_companies": top_companies,
    }


@router.get("/salary")
@limiter.limit("20/minute")
async def salary_stats(
    request: Request,
    role: Optional[str] = Query(None, description="Free-text role (e.g. backend, python, react)"),
    seniority: Optional[str] = Query(None, description="Our seniority enum (intern/junior/mid/senior/lead/executive)"),
    yoe_from: Optional[int] = Query(None, ge=0, le=20, description="Min years of experience (inclusive)"),
    yoe_to: Optional[int] = Query(None, ge=1, le=26, description="Max years of experience (exclusive)"),
):
    """Egyptian tech salary statistics, sourced from egytech.fyi (April 2024 survey)."""
    empty = {
        "currency": "EGP",
        "period": "monthly",
        "source": "egytech.fyi April 2024 survey",
        "stats": None,
        "buckets": [],
        "filters": {"role": role, "seniority": seniority, "yoe_from": yoe_from, "yoe_to": yoe_to},
        "matched": False,
    }

    title = parse_role_query(role) if role else None
    if not title:
        if role:
            log.info("salary stats: unmapped role=%r", role)
        return empty

    level = SENIORITY_TO_LEVEL.get(seniority) if seniority else None

    data = get_stats(title=title, level=level, yoe_from=yoe_from, yoe_to=yoe_to)
    if not data or "stats" not in data:
        return empty

    s = data["stats"]
    return {
        "currency": "EGP",
        "period": "monthly",
        "source": "egytech.fyi April 2024 survey",
        "stats": {
            "sample_size": s.get("totalCount", 0),
            "median": s.get("median"),
            "p20": s.get("p20Compensation"),
            "p75": s.get("p75Compensation"),
            "p90": s.get("p90Compensation"),
        },
        "buckets": [
            {"label": b.get("bucket", ""), "count": b.get("count", 0)}
            for b in data.get("buckets", [])
            if isinstance(b, dict)
        ],
        "filters": {"role": role, "seniority": seniority, "yoe_from": yoe_from, "yoe_to": yoe_to},
        "matched": True,
    }


@router.get("/trends")
@limiter.limit("20/minute")
async def skill_trends(
    request: Request,
    period: str = Query("7d", description="Period: 7d, 14d, 30d"),
):
    """Skill trends with week-over-week change."""
    days = {"7d": 7, "14d": 14, "30d": 30}.get(period, 7)

    # Current period
    current = db._fetchall(
        """SELECT unnest(tags) as skill, COUNT(*) as count
           FROM jobs WHERE created_at > now() - make_interval(days := %s)
           GROUP BY skill ORDER BY count DESC LIMIT 20""",
        (days,),
    )

    # Previous period (for comparison)
    previous = db._fetchall(
        """SELECT unnest(tags) as skill, COUNT(*) as count
           FROM jobs WHERE created_at BETWEEN
             now() - make_interval(days := %s)
             AND now() - make_interval(days := %s)
           GROUP BY skill ORDER BY count DESC LIMIT 20""",
        (days * 2, days),
    )

    prev_map = {r["skill"]: r["count"] for r in previous}
    trends = []
    for row in current:
        skill = row["skill"]
        current_count = row["count"]
        prev_count = prev_map.get(skill, 0)
        change = ((current_count - prev_count) / max(prev_count, 1)) * 100
        trends.append({
            "skill": skill,
            "count": current_count,
            "previous_count": prev_count,
            "change_percent": round(change, 1),
        })

    return {"period": period, "trends": trends}
