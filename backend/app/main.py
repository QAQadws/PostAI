from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.middleware import RequestLoggingMiddleware
from app.api.routes_generate import router as generate_router
from app.core.config import get_settings, resolve_asset_dir
from app.core.logging import setup_logging


def create_app() -> FastAPI:
    settings = get_settings()

    setup_logging(
        log_level=settings.log_level,
        log_file=settings.log_file or None,
    )

    app = FastAPI(title=settings.app_name, version=settings.app_version)

    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    asset_dir = resolve_asset_dir(settings.asset_dir)
    asset_dir.mkdir(parents=True, exist_ok=True)
    app.mount(settings.asset_url_path, StaticFiles(directory=str(asset_dir)), name="assets")
    app.include_router(generate_router, prefix="/api/v1")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
