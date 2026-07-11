from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.router import api_router
from app.core.config import settings

app = FastAPI(title=settings.app_name)
app.include_router(api_router, prefix=settings.api_prefix)


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
