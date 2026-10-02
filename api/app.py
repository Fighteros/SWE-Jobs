"""
FastAPI application factory.
Serves the dashboard API endpoints with CORS and rate limiting.
"""

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from api.middleware import limiter


def create_app(lifespan=None) -> FastAPI:
    app = FastAPI(title="SWE-Jobs API", version="2.0.0", lifespan=lifespan)

    # Rate limiting
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # CORS — exact dashboard origins allowlist with credentials.
    # Never use wildcard credentialed CORS in production.
    origins = os.getenv("DASHBOARD_ORIGINS", "http://localhost:5173")
    allow_origins = [o.strip() for o in origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    # Register routes
    from api.routes_jobs import router as jobs_router
    from api.routes_stats import router as stats_router
    from api.routes_auth import router as auth_router
    app.include_router(jobs_router, prefix="/api/jobs")
    app.include_router(stats_router, prefix="/api/stats")
    app.include_router(auth_router)

    @app.get("/health")
    async def health():
        # Includes supervised-polling liveness so the Docker healthcheck (and
        # humans) can tell a bot-down backend from a healthy one.
        from bot.polling import get_supervisor_status

        return {"status": "ok", "telegram": get_supervisor_status()}

    @app.get("/livez")
    async def livez():
        """Liveness probe — no auth required."""
        return {"status": "alive"}

    return app
