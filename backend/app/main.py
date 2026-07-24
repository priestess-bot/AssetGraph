from urllib.parse import urlencode

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
maitu_dist = frontend_dist / "maitu"


def _redirect_query(request: Request, *, excluded: set[str], appended: tuple[tuple[str, str], ...] = ()) -> str:
    items = [(key, value) for key, value in request.query_params.multi_items() if key not in excluded]
    items.extend(appended)
    return f"?{urlencode(items)}" if items else ""


@app.api_route("/maitu", methods=["GET", "HEAD"], include_in_schema=False)
@app.api_route("/maitu/", methods=["GET", "HEAD"], include_in_schema=False)
def legacy_maitu_frontend(request: Request) -> RedirectResponse:
    view = request.query_params.get("view")
    if view == "resources":
        target = "/assets/library"
        query = _redirect_query(request, excluded={"view"})
    elif view == "gemini":
        target = "/assets/library"
        query = _redirect_query(request, excluded={"view", "panel"}, appended=(("panel", "analysis"),))
    else:
        target = "/production/live-rooms"
        query = _redirect_query(request, excluded={"view"})
    return RedirectResponse(url=f"{target}{query}", status_code=status.HTTP_308_PERMANENT_REDIRECT)


@app.api_route("/live-research", methods=["GET", "HEAD"], include_in_schema=False)
@app.api_route("/live-research/", methods=["GET", "HEAD"], include_in_schema=False)
def legacy_live_research_frontend(request: Request) -> RedirectResponse:
    view = request.query_params.get("view")
    appended = (("view", view),) if view in {"sessions", "drafts", "published"} else ()
    query = _redirect_query(request, excluded={"view"}, appended=appended)
    return RedirectResponse(
        url=f"/research/live-sources{query}",
        status_code=status.HTTP_308_PERMANENT_REDIRECT,
    )


if maitu_dist.is_dir():
    app.mount("/maitu", StaticFiles(directory=maitu_dist, html=True), name="maitu-production-workbench")

live_research_dist = frontend_dist / "live-research"
if live_research_dist.is_dir():
    app.mount(
        "/live-research",
        StaticFiles(directory=live_research_dist, html=True),
        name="live-research-workbench",
    )

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
        "/governance",
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
