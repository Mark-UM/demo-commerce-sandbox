import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException

from app.database import Store
from app.errors import SourceError
from app.routers import admin, logistics, oms, policy, simulation, support, warehouse
from app.schemas import ErrorResponse
from app.security import authenticate


def create_app(db_path: str | None = None, api_key: str | None = None) -> FastAPI:
    database = Store(db_path or os.getenv("SANDBOX_DB_PATH", "sandbox.sqlite3"))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        database.initialize()
        yield

    app = FastAPI(title="DemoCommerce Sandbox", version="0.1.0", lifespan=lifespan)
    static = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=static), name="static")

    @app.get("/", include_in_schema=False)
    def console():
        return FileResponse(static / "index.html")

    app.state.store = database
    app.state.api_key = (
        os.getenv("SANDBOX_API_KEY", "demo-commerce-key")
        if api_key is None
        else api_key
    )

    @app.middleware("http")
    async def request_id(request: Request, call_next):
        started = time.perf_counter()
        request.state.request_id = request.headers.get("X-Request-Id") or str(uuid4())
        response = await call_next(request)
        response.headers["X-Request-Id"] = request.state.request_id
        logging.getLogger("uvicorn.error").info(
            "sandbox_request method=%s path=%s status=%s latency_ms=%.1f request_id=%r",
            request.method,
            request.url.path,
            response.status_code,
            (time.perf_counter() - started) * 1000,
            request.state.request_id,
        )
        return response

    def error_response(request, status, code, message, headers=None):
        correlation = getattr(request.state, "request_id", "unknown")
        return JSONResponse(
            status_code=status,
            headers={**(headers or {}), "X-Request-Id": correlation},
            content={
                "error": {
                    "code": code,
                    "message": message,
                    "request_id": correlation,
                }
            },
        )

    @app.exception_handler(SourceError)
    async def source_error(request: Request, exc: SourceError):
        return error_response(request, exc.status, exc.code, exc.message, exc.headers)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError):
        return error_response(
            request, 422, "INVALID_REQUEST", "Invalid request payload"
        )

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        return error_response(request, exc.status_code, "HTTP_ERROR", str(exc.detail))

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception):
        logging.getLogger("uvicorn.error").error(
            "sandbox_internal_error request_id=%r type=%s",
            getattr(request.state, "request_id", "unknown"),
            type(exc).__name__,
        )
        return error_response(request, 500, "INTERNAL_ERROR", "Sandbox internal error")

    @app.get("/health")
    def health():
        with database.connect() as db:
            version = db.execute("SELECT version FROM metadata").fetchone()[0]
        return {"status": "ok", "database": "ok", "seed_version": version}

    for router in (
        oms.router,
        logistics.router,
        warehouse.router,
        policy.router,
        support.router,
        admin.router,
        simulation.router,
    ):
        app.include_router(
            router,
            dependencies=[Depends(authenticate)],
            responses={
                status: {"model": ErrorResponse}
                for status in (401, 403, 404, 409, 422, 429, 500, 503, 504)
            },
        )
    return app


app = create_app()
