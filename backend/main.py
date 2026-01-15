from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

import settings
from admin_routes import router as admin_router
from lifecycle import shutdown_event, startup_event
from middleware import add_cors_headers, add_security_headers, log_requests
from rate_limiter import get_limiter
from routes import router as api_router
from utils.logger import get_logger
from utils.path_setup import setup_local_bin_path

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await startup_event()
    yield
    await shutdown_event()


def create_app(rate_limit_enabled_override: bool | None = None) -> FastAPI:
    local_bin = setup_local_bin_path()
    if local_bin:
        logger.info(f"Added local bin to PATH: {local_bin}")

    cfg = settings.get_settings()
    limiter = get_limiter()
    rate_limit_enabled = (
        cfg.rate_limit_enabled
        if rate_limit_enabled_override is None
        else rate_limit_enabled_override
    )
    limiter.enabled = rate_limit_enabled

    app = FastAPI(title="ShadowPartner API", lifespan=lifespan)
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    if rate_limit_enabled:
        logger.info(
            f"Rate limiting enabled - "
            f"default: {cfg.rate_limit_default_requests_per_minute}/min, "
            f"upload: {cfg.rate_limit_upload_per_minute}/min, "
            f"process: {cfg.rate_limit_process_per_minute}/min, "
            f"status: {cfg.rate_limit_status_per_minute}/min, "
            f"health: {cfg.rate_limit_health_check_per_minute}/min"
        )
    else:
        if rate_limit_enabled_override is None:
            logger.info("Rate limiting disabled")
        else:
            logger.info("Rate limiting disabled via startup override")

    app.middleware("http")(log_requests)
    app.middleware("http")(add_security_headers)
    app.middleware("http")(add_cors_headers)
    app.include_router(api_router)
    app.include_router(admin_router)
    return app


app = create_app()


if __name__ == "__main__":
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser(description="ShadowPartner API server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    parser.add_argument(
        "--no-rate-limit",
        action="store_true",
        help="Disable API rate limiting (useful for tests).",
    )
    args = parser.parse_args()
    override = False if args.no_rate_limit else None
    uvicorn.run(
        create_app(rate_limit_enabled_override=override),
        host=args.host,
        port=args.port,
        reload=args.reload,
    )
