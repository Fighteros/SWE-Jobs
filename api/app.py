"""
FastAPI application factory.
Serves the public API with rate limiting.
"""

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from api.middleware import limiter


def create_app(lifespan=None) -> FastAPI:
    app = FastAPI(title="SWE-Jobs API", version="2.0.0", lifespan=lifespan)

    # Rate limiting
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # Register routes
    from api.routes_jobs import router as jobs_router
    from api.routes_stats import router as stats_router
    app.include_router(jobs_router, prefix="/api/jobs")
    app.include_router(stats_router, prefix="/api/stats")

    @app.get("/health")
    async def health():
        # 503 while the polling supervisor is not running, so the Docker
        # healthcheck (and autoheal) treats a bot-down backend as unhealthy
        # instead of silently serving 200. Mid-recovery still counts as alive:
        # the supervisor is actively rebuilding the poller then.
        from bot.polling import get_supervisor_status, supervisor_alive

        alive = supervisor_alive()
        return JSONResponse(
            {
                "status": "ok" if alive else "unhealthy",
                "telegram": get_supervisor_status(),
            },
            status_code=200 if alive else 503,
        )

    return app
