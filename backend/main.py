from fastapi import FastAPI
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

import settings
from lifecycle import shutdown_event, startup_event
from middleware import add_cors_headers, log_requests
from rate_limiter import get_limiter
from routes import router as api_router
from utils.logger import get_logger
from utils.path_setup import setup_local_bin_path

logger = get_logger(__name__)


def create_app() -> FastAPI:
    local_bin = setup_local_bin_path()
    if local_bin:
        logger.info(f"Added local bin to PATH: {local_bin}")

    cfg = settings.get_settings()
    limiter = get_limiter()

    app = FastAPI(title="ShadowPartner API")
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    if cfg.rate_limit_enabled:
        logger.info(
            f"Rate limiting enabled - "
            f"default: {cfg.rate_limit_default_requests_per_minute}/min, "
            f"upload: {cfg.rate_limit_upload_per_minute}/min, "
            f"process: {cfg.rate_limit_process_per_minute}/min, "
            f"status: {cfg.rate_limit_status_per_minute}/min, "
            f"health: {cfg.rate_limit_health_check_per_minute}/min"
        )
    else:
        logger.info("Rate limiting disabled")

    app.on_event("startup")(startup_event)
    app.on_event("shutdown")(shutdown_event)
    app.middleware("http")(log_requests)
    app.middleware("http")(add_cors_headers)
    app.include_router(api_router)
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
