from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.router import api_router
from app.core.config import REPO_ROOT, settings

app = FastAPI(title=settings.app_name)
app.include_router(api_router, prefix=settings.api_prefix)

frontend_dist = REPO_ROOT / "frontend" / "dist"
maitu_dist = frontend_dist / "maitu"
if maitu_dist.is_dir():
    app.mount("/maitu", StaticFiles(directory=maitu_dist, html=True), name="maitu-production-workbench")

live_research_dist = frontend_dist / "live-research"
if live_research_dist.is_dir():
    app.mount(
        "/live-research",
        StaticFiles(directory=live_research_dist, html=True),
        name="live-research-workbench",
    )


@app.exception_handler(RequestValidationError)
async def sanitized_request_validation_error(
    _request: Request,
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
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"detail": safe_errors},
    )


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    return {"status": "ok"}
