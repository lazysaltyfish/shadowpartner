from fastapi import FastAPI

from lifecycle import shutdown_event, startup_event
from middleware import add_cors_headers, log_requests
from routes import router as api_router
from utils.logger import get_logger
from utils.path_setup import setup_local_bin_path

logger = get_logger(__name__)


def create_app() -> FastAPI:
    local_bin = setup_local_bin_path()
    if local_bin:
        logger.info(f"Added local bin to PATH: {local_bin}")

    app = FastAPI(title="ShadowPartner API")
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
