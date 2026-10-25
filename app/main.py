"""조직검체 장부 진입점.

CORIOPS_DATABASE_URL이 있으면 PostgreSQL에 저장하고 **개인 계정 로그인·접속기록이 항상 켜진다.**
없으면 합성 seed를 쓰는 메모리 시연이며 로그인 없이 '시연 사용자'로 동작한다.
원장 결재 전에는 실제 환자 자료를 넣지 않는다.
"""

from pathlib import Path
import os
import secrets

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool
from starlette.formparsers import MultiPartParser
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.kernel.access_log import AccessLogger
from app.kernel.auth import AuthService
from app.kernel.routes_auth import router as auth_router
from app.kernel.web import SESSION_COOKIE, UserError, demo_actor, same_origin
from app.modules.endoscopy_pathology.ledger_db import PostgresStore
from app.modules.endoscopy_pathology.manual_dashboard import ManualDashboardService
from app.modules.endoscopy_pathology.routes_manual_dashboard import router
from app.modules.screening_lab.dashboard import LabDashboardService
from app.modules.screening_lab.routes_dashboard import router as lab_router


PUBLIC_PATHS = ("/login",)
PASSWORD_PATHS = ("/account/password", "/logout")


def default_service() -> ManualDashboardService:
    if os.environ.get("CORIOPS_DATABASE_URL"):
        return ManualDashboardService(store=PostgresStore())
    return ManualDashboardService()


def create_app(service: ManualDashboardService | None = None, csrf_token: str | None = None,
               auth: AuthService | None = None, access_log: AccessLogger | None = None,
               lab_service: LabDashboardService | None = None) -> FastAPI:
    app = FastAPI(title="CoriOps Nexus · 조직검체 장부", docs_url=None, redoc_url=None, openapi_url=None)
    service = service or default_service()
    app.state.dashboard_service = service
    if service.persistent:
        # DB에 저장하는 한 로그인·접속기록을 끌 수 없다.
        engine = service.engine
        app.state.auth = auth or AuthService(engine)
        app.state.access_log = access_log or AccessLogger(engine)
    else:
        app.state.auth, app.state.access_log = None, None
    # 혈액검체 탭은 아직 저장소가 없는 합성 시연이므로 DB 모드에서는 조립하지 않는다.
    app.state.lab_service = None if service.persistent else (lab_service or LabDashboardService())
    # 업로드 엑셀이 임시 디스크 파일로 넘어가지 않게, 허용 크기까지 메모리에 둔다.
    MultiPartParser.spool_max_size = max(MultiPartParser.spool_max_size, service.max_upload_bytes + 64 * 1024)
    app.state.csrf_token = csrf_token or secrets.token_urlsafe(32)
    web = Path(__file__).parent / "web"
    app.state.templates = Jinja2Templates(directory=web / "templates")
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])

    def error_page(request: Request, message: str, status_code: int):
        return app.state.templates.TemplateResponse(
            request=request, name="manual_error.html", context={"message": message}, status_code=status_code)

    @app.middleware("http")
    async def security(request: Request, call_next):
        if request.method == "POST" and not same_origin(request):
            return error_page(request, "다른 사이트에서 보낸 요청은 받지 않습니다.", 403)
        path = request.url.path
        if app.state.auth is None:
            request.state.actor = demo_actor(app.state.csrf_token)
            return await call_next(request)
        token = request.cookies.get(SESSION_COOKIE, "")
        actor = await run_in_threadpool(app.state.auth.resolve, token) if token else None
        request.state.actor = actor
        if path.startswith("/static/") or path in PUBLIC_PATHS:
            return await call_next(request)
        if actor is None:
            if request.method == "GET":
                response = RedirectResponse("/login?notice=expired" if token else "/login", status_code=303)
                response.delete_cookie(SESSION_COOKIE, path="/")
                return response
            return error_page(request, "로그인이 필요합니다. 다시 로그인해 주세요.", 401)
        if actor.must_change_password and path not in PASSWORD_PATHS:
            return RedirectResponse("/account/password", status_code=303)
        return await call_next(request)

    @app.middleware("http")
    async def local_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"  # no-referrer면 같은 사이트 POST의 Origin이 null이 된다
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; style-src 'self'; img-src 'self' data:; "
            "form-action 'self'; base-uri 'none'; frame-ancestors 'none'; connect-src 'none'"
        )
        return response

    @app.exception_handler(UserError)
    async def user_error(request: Request, error: UserError):
        return error_page(request, error.message, error.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError):
        # 제출 내용을 에러 화면·로그에 되비추지 않는다.
        return error_page(request, "입력 형식을 확인해 주세요.", 422)

    app.mount("/static", StaticFiles(directory=web / "static"), name="static")
    app.include_router(auth_router)
    app.include_router(router)
    if app.state.lab_service is not None:
        app.include_router(lab_router)
    return app


app = create_app()
