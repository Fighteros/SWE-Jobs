"""Job search and listing endpoints."""

from fastapi import APIRouter, Query, Request
from typing import Optional
from api.middleware import limiter
from core import db

router = APIRouter()


@router.get("/search")
@limiter.limit("30/minute")
async def search_jobs(
    request: Request,
    q: Optional[str] = Query(None, description="Search query"),
    topic: Optional[str] = Query(None, description="Filter by topic"),
    seniority: Optional[str] = Query(None, description="Filter by seniority"),
    remote: Optional[bool] = Query(None, description="Remote only"),
    country: Optional[str] = Query(None, description="Country ISO code"),
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(20, ge=1, le=50, description="Items per page"),
):
    """Search and filter jobs."""
    from core.egytech import market_salary_for_job
    from core.models import Job

    conditions_sql = ["sent_at IS NOT NULL"]
    params_sql = []

    if q:
        conditions_sql.append("(title ILIKE %s OR %s = ANY(tags))")
        params_sql.extend([f"%{q}%", q.lower()])
    if topic:
        conditions_sql.append("%s = ANY(topics)")
        params_sql.append(topic)
    if seniority:
        conditions_sql.append("seniority = %s")
        params_sql.append(seniority)
    if remote:
        conditions_sql.append("is_remote = TRUE")
    if country:
        conditions_sql.append("country = %s")
        params_sql.append(country)

    where_sql = " AND ".join(conditions_sql)
    offset = (page - 1) * per_page

    # Count total
    count_row = db._fetchone(
        f"SELECT COUNT(*) as total FROM jobs WHERE {where_sql}",
        tuple(params_sql),
    )
    total = count_row["total"] if count_row else 0

    # Fetch page
    rows = db._fetchall(
        f"""SELECT id, title, company, location, url, source, original_source,
                   salary_raw, salary_min, salary_max, salary_currency,
                   job_type, seniority, is_remote, country, tags, topics, created_at
            FROM jobs WHERE {where_sql}
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s""",
        tuple(params_sql) + (per_page, offset),
    )

    # Enrich each row with the egytech market reference (cache-backed; cheap after warmup).
    for row in rows:
        try:
            job = Job.from_db_row(row)
            row["market_salary"] = market_salary_for_job(job)
        except Exception:
            row["market_salary"] = None

    return {
        "jobs": rows,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": (total + per_page - 1) // per_page if total else 0,
    }
