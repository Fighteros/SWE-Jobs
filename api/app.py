"""
FastAPI application factory.
Serves the public API with rate limiting.
"""

from fastapi import FastAPI
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
        # Includes supervised-polling liveness so the Docker healthcheck (and
        # humans) can tell a bot-down backend from a healthy one.
        from bot.polling import get_supervisor_status

        return {"status": "ok", "telegram": get_supervisor_status()}

    return app
