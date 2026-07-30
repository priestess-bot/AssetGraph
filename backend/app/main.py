from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.router import api_router
from app.core.config import REPO_ROOT, settings
from app.core.problems import problem_payload
from app.core.telemetry import configure_telemetry, trace_context_from_current

app = FastAPI(title=settings.app_name)
app.include_router(api_router, prefix=settings.api_prefix)


class ConsoleStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope: dict) -> Response:
        try:
            response = await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != status.HTTP_404_NOT_FOUND:
                raise
            response = JSONResponse(status_code=exc.status_code, content={"detail": "Not Found"})
        if (
            response.status_code == status.HTTP_404_NOT_FOUND
            and scope.get("method") in ("GET", "HEAD")
            and not path.rsplit("/", 1)[-1].count(".")
        ):
            return await super().get_response("index.html", scope)
        return response

frontend_dist = REPO_ROOT / "frontend" / "dist"
console_dist = frontend_dist / "console"
if console_dist.is_dir():
    app.mount("/console", ConsoleStaticFiles(directory=console_dist, html=True), name="assetgraph-console")
    for stable_prefix in (
        "/assets",
        "/knowledge",
        "/research",
        "/content",
        "/production",
        "/operations",
        "/learning",
    ):
        app.mount(
            stable_prefix,
            ConsoleStaticFiles(directory=console_dist, html=True),
            name=f"assetgraph-console-{stable_prefix[1:]}",
        )


def _current_trace_id() -> str | None:
    current = trace_context_from_current()
    return current.trace_id if current is not None else None


@app.exception_handler(StarletteHTTPException)
async def structured_http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    trace_id = _current_trace_id()
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "detail": exc.detail,
            "error": problem_payload(
                status_code=exc.status_code,
                detail=exc.detail,
                request_path=request.url.path,
                trace_id=trace_id,
            ),
        },
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def sanitized_request_validation_error(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    safe_errors = []
    for error in exc.errors():
        location = error.get("loc") or ("request",)
        safe_errors.append(
            {
                "type": error.get("type", "request_validation_error"),
                "loc": [location[0]],
                "msg": "Invalid request value",
            }
        )
    detail = safe_errors
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={
            "detail": detail,
            "error": problem_payload(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"message": "Invalid request value", "code": "REQUEST_VALIDATION_FAILED"},
                request_path=request.url.path,
                trace_id=_current_trace_id(),
            ),
        },
    )


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
def console_home() -> RedirectResponse:
    return RedirectResponse(url="/console/", status_code=status.HTTP_307_TEMPORARY_REDIRECT)


configure_telemetry(
    app,
    service_name=settings.otel_service_name,
    environment=settings.app_env,
    exporter_endpoint=settings.otel_exporter_otlp_endpoint,
)
