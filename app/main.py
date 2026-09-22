import os
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from app.database import Store
from app.errors import SourceError
from app.routers import logistics, oms, support, warehouse
from app.schemas import ErrorResponse


def create_app(db_path: str | None = None) -> FastAPI:
    database = Store(db_path or os.getenv("SANDBOX_DB_PATH", "sandbox.sqlite3"))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        database.initialize()
        yield

    app = FastAPI(title="DemoCommerce Sandbox", version="0.1.0", lifespan=lifespan)
    app.state.store = database

    @app.middleware("http")
    async def request_id(request: Request, call_next):
        request.state.request_id = request.headers.get("X-Request-Id") or str(uuid4())
        response = await call_next(request)
        response.headers["X-Request-Id"] = request.state.request_id
        return response

    def error_response(request, status, code, message):
        return JSONResponse(
            status_code=status,
            content={
                "error": {
                    "code": code,
                    "message": message,
                    "request_id": request.state.request_id,
                }
            },
        )

    @app.exception_handler(SourceError)
    async def source_error(request: Request, exc: SourceError):
        return error_response(request, exc.status, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError):
        return error_response(
            request, 422, "INVALID_REQUEST", "Invalid request payload"
        )

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        return error_response(request, exc.status_code, "HTTP_ERROR", str(exc.detail))

    @app.get("/health")
    def health():
        with database.connect() as db:
            version = db.execute("SELECT version FROM metadata").fetchone()[0]
        return {"status": "ok", "database": "ok", "seed_version": version}

    for router in (oms.router, logistics.router, warehouse.router, support.router):
        app.include_router(
            router,
            responses={
                status: {"model": ErrorResponse} for status in (404, 409, 422, 503, 504)
            },
        )
    return app


app = create_app()
