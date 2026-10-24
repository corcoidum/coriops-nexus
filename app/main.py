"""실환자 자료를 받지 않는 로컬 합성 대시보드 진입점."""

from pathlib import Path
import secrets

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.modules.endoscopy_pathology.manual_dashboard import DashboardError, ManualDashboardService
from app.modules.endoscopy_pathology.routes_manual_dashboard import router


def create_app(service: ManualDashboardService | None = None, csrf_token: str | None = None) -> FastAPI:
    app = FastAPI(title="CoriOps Nexus · 합성 시연", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.dashboard_service = service or ManualDashboardService()
    app.state.csrf_token = csrf_token or secrets.token_urlsafe(32)
    web = Path(__file__).parent / "web"
    app.state.templates = Jinja2Templates(directory=web / "templates")
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])

    @app.middleware("http")
    async def local_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; style-src 'self'; img-src 'self' data:; "
            "form-action 'self'; base-uri 'none'; frame-ancestors 'none'; connect-src 'none'"
        )
        return response

    @app.exception_handler(DashboardError)
    async def dashboard_error(request: Request, error: DashboardError):
        return app.state.templates.TemplateResponse(
            request=request, name="manual_error.html",
            context={"message": error.message}, status_code=error.status_code,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError):
        # 제출 내용을 에러 화면·로그에 되비추지 않는다.
        return app.state.templates.TemplateResponse(
            request=request, name="manual_error.html",
            context={"message": "입력 형식을 확인해 주세요."}, status_code=422,
        )

    app.mount("/static", StaticFiles(directory=web / "static"), name="static")
    app.include_router(router)
    return app


app = create_app()
