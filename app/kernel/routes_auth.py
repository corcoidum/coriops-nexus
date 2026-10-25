"""로그인·로그아웃·비밀번호·계정 관리·접속기록 화면. 장부 업무 모듈을 import하지 않는다."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Annotated
from urllib.parse import urlencode
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from starlette.concurrency import run_in_threadpool

from app.kernel.access_log import ACTION_LABELS
from app.kernel.auth import ROLE_LABELS, AuthError, AuthService
from app.kernel.security_db import ROLES
from app.kernel.web import SESSION_COOKIE, UserError, audit, check_csrf, client_ip, current_actor, render, require


router = APIRouter()
KST = ZoneInfo("Asia/Seoul")


def auth_service(request: Request) -> AuthService:
    auth = request.app.state.auth
    if auth is None:
        raise UserError("시연 모드에는 계정 기능이 없습니다.", 404)
    return auth


def see_other(path: str, **params) -> RedirectResponse:
    query = urlencode({k: v for k, v in params.items() if v not in (None, "")})
    return RedirectResponse(f"{path}?{query}" if query else path, status_code=303)


def as_user_error(error: AuthError) -> UserError:
    return UserError(error.message, error.status_code)


# ---------- 로그인

@router.get("/login")
def login_page(request: Request, notice: str = ""):
    if request.app.state.auth is None or getattr(request.state, "actor", None):
        return see_other("/dashboard")
    messages = {"logout": "로그아웃했습니다.", "expired": "오래 사용하지 않아 로그아웃됐습니다. 다시 로그인해 주세요."}
    return render(request, "login.html", {"notice": messages.get(notice, "")})


@router.post("/login")
async def login(request: Request, username: Annotated[str, Form()] = "", password: Annotated[str, Form()] = ""):
    auth = auth_service(request)
    try:
        actor, token = await run_in_threadpool(auth.login, username, password)
    except AuthError as error:
        # 입력한 아이디 원문은 남기지 않는다. 등록된 계정이면 그 계정 UUID만 남긴다.
        failure = {"actor_id": error.staff_id, "actor_label": "known-account" if error.staff_id else "unknown",
                   "client_ip": client_ip(request), "action": "LOGIN_FAIL", "target_type": "login",
                   "outcome": error.code}
        await run_in_threadpool(lambda: request.app.state.access_log.record(**failure))
        return render(request, "login.html", {"error": error.message}, status_code=error.status_code)
    audit(request, "LOGIN", "login", actor=actor)
    response = see_other("/account/password" if actor.must_change_password else "/dashboard")
    response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="strict", secure=auth.policy.cookie_secure,
                        path="/")
    return response


@router.post("/logout")
def logout(request: Request, csrf_token: Annotated[str, Form()] = ""):
    auth = auth_service(request)
    check_csrf(request, csrf_token)
    audit(request, "LOGOUT", "login")
    auth.logout(request.cookies.get(SESSION_COOKIE, ""))
    response = see_other("/login", notice="logout")
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@router.get("/account/password")
def password_page(request: Request):
    auth_service(request)
    return render(request, "account_password.html", {})


@router.post("/account/password")
def change_password(request: Request, csrf_token: Annotated[str, Form()] = "",
                    current: Annotated[str, Form()] = "", new: Annotated[str, Form()] = "",
                    confirm: Annotated[str, Form()] = ""):
    auth = auth_service(request)
    check_csrf(request, csrf_token)
    actor = current_actor(request)
    if new != confirm:
        raise UserError("새 비밀번호 두 칸이 서로 다릅니다.", 422)
    try:
        auth.change_password(actor, current, new, request.cookies.get(SESSION_COOKIE, ""))
    except AuthError as error:
        raise as_user_error(error) from None
    audit(request, "ACCOUNT", f"password:{actor.username}")
    return see_other("/dashboard")


# ---------- 계정 관리 (개인정보 책임자)

@router.get("/admin/staff")
def staff_page(request: Request, notice: str = ""):
    auth = auth_service(request)
    require(request, "admin.staff")
    audit(request, "ACCOUNT", "staff_list")
    return render(request, "admin_staff.html", {
        "staff": auth.list_staff(), "roles": ROLES, "role_labels": ROLE_LABELS,
        "permissions": auth.policy.permissions, "min_length": auth.policy.min_password_length,
        "notice": {"created": "계정을 만들었습니다.", "changed": "변경했습니다. 대상자의 접속은 모두 끊겼습니다."}.get(notice, ""),
    })


@router.post("/admin/staff")
def create_staff(request: Request, csrf_token: Annotated[str, Form()] = "", username: Annotated[str, Form()] = "",
                 display_name: Annotated[str, Form()] = "", roles: Annotated[list[str], Form()] = (),
                 password: Annotated[str, Form()] = "", reason: Annotated[str, Form()] = ""):
    auth = auth_service(request)
    check_csrf(request, csrf_token)
    actor = require(request, "admin.staff")
    try:
        auth.create_staff(username, display_name, roles, password, changed_by=actor.staff_id, reason=reason)
    except AuthError as error:
        raise as_user_error(error) from None
    audit(request, "ACCOUNT", f"staff_create:{username.strip().lower()[:30]}")
    return see_other("/admin/staff", notice="created")


@router.post("/admin/staff/{staff_id}/{change}")
def change_staff(request: Request, staff_id: UUID, change: str, csrf_token: Annotated[str, Form()] = "",
                 roles: Annotated[list[str], Form()] = (), active: Annotated[str, Form()] = "",
                 password: Annotated[str, Form()] = "", reason: Annotated[str, Form()] = ""):
    auth = auth_service(request)
    check_csrf(request, csrf_token)
    actor = require(request, "admin.staff")
    target = next((s for s in auth.list_staff() if s.id == staff_id), None)
    if target is None:
        raise UserError("계정을 찾을 수 없습니다.", 404)
    try:
        if change == "roles":
            auth.set_roles(staff_id, roles, by=actor, reason=reason)
        elif change == "active":
            auth.set_active(staff_id, active == "1", by=actor, reason=reason)
        elif change == "reset":
            auth.reset_password(staff_id, password, by=actor, reason=reason)
        else:
            raise UserError("알 수 없는 변경입니다.", 404)
    except AuthError as error:
        raise as_user_error(error) from None
    audit(request, "ACCOUNT", f"staff_{change}:{target.username}")
    return see_other("/admin/staff", notice="changed")


# ---------- 접속기록 (개인정보 책임자)

def _period(start: str, end: str) -> tuple[date, date, datetime, datetime]:
    today = datetime.now(KST).date()
    try:
        first = date.fromisoformat(start) if start else today - timedelta(days=6)
        last = date.fromisoformat(end) if end else today
    except ValueError:
        raise UserError("날짜 형식을 확인해 주세요.", 422) from None
    if last < first or (last - first).days > 366:
        raise UserError("기간은 1년 이내로 지정해 주세요.", 422)
    return first, last, datetime.combine(first, time.min, KST), datetime.combine(last + timedelta(days=1), time.min, KST)


@router.get("/privacy/access-logs")
def access_logs_page(request: Request, start: str = "", end: str = "", actor: str = "", subject: str = "",
                     action: str = "", page: int = 1, notice: str = ""):
    auth_service(request)
    require(request, "privacy.logs")
    if action and action not in ACTION_LABELS:
        raise UserError("알 수 없는 업무 구분입니다.", 422)
    first, last, since, until = _period(start, end)
    logger = request.app.state.access_log
    # 점검 화면을 연 것도 기록한다(조회 조건의 정보주체 포함).
    audit(request, "LOG_VIEW", "access_logs", subjects=[subject.strip()[:20]] if subject.strip() else None)
    rows, total = logger.search(since, until, actor.strip()[:40], subject.strip()[:20], action, page)
    return render(request, "access_logs.html", {
        "rows": rows, "total": total, "page": max(page, 1), "pages": max(1, -(-total // 100)),
        "first": first, "last": last, "filters": {"actor": actor, "subject": subject, "action": action},
        "chain": logger.verify(), "alerts": logger.bulk_alerts(since, until), "reviews": logger.reviews(),
        "action_labels": ACTION_LABELS, "policy": logger.policy, "kst": KST,
        "notice": "점검 결과를 기록했습니다." if notice == "reviewed" else "",
    })


@router.post("/privacy/access-logs/review")
def review_access_logs(request: Request, csrf_token: Annotated[str, Form()] = "", start: Annotated[str, Form()] = "",
                       end: Annotated[str, Form()] = "", note: Annotated[str, Form()] = ""):
    auth_service(request)
    check_csrf(request, csrf_token)
    actor = require(request, "privacy.logs")
    first, last, since, until = _period(start, end)
    clean = note.strip()
    if not clean or len(clean) > 200:
        raise UserError("점검 의견을 1~200자로 입력해 주세요. 환자 이름·연락처는 쓰지 않습니다.", 422)
    request.app.state.access_log.add_review(actor.staff_id, since, until, clean)
    audit(request, "LOG_REVIEW", "access_logs")
    return see_other("/privacy/access-logs", start=first.isoformat(), end=last.isoformat(), notice="reviewed")
