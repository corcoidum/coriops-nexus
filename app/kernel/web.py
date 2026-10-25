"""화면 공통: 현재 사용자, CSRF, 권한 확인, 접속기록, 렌더링. 업무 모듈을 알지 못한다."""

from __future__ import annotations

import secrets

from fastapi import Request

from app.kernel.auth import Actor


SESSION_COOKIE = "coriops_session"
DEMO_ROLES = frozenset({"DOCTOR", "ADMIN", "NURSE"})


class UserError(Exception):
    """사용자에게 보여줄 수 있는 메시지. 입력값을 되비추지 않는다."""

    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def demo_actor(csrf_token: str) -> Actor:
    return Actor(None, "demo", "시연 사용자", DEMO_ROLES, csrf_token, demo=True)


def current_actor(request: Request) -> Actor:
    actor = getattr(request.state, "actor", None)
    if actor is None:
        raise UserError("로그인이 필요합니다.", 401)
    return actor


def client_ip(request: Request) -> str:
    # DB 모드에서는 접속 대역 검사(app/kernel/network.py)가 신뢰 프록시를 반영해 정한 주소를 쓴다.
    resolved = getattr(request.state, "client_ip", None)
    if resolved:
        return resolved
    return request.client.host if request.client else "unknown"


def audit(request: Request, action: str, target_type: str, subjects: list[str] | None = None,
          count: int | None = None, outcome: str = "OK", actor: Actor | None = None) -> None:
    """DB 모드에서만 접속기록을 남긴다. 기록 실패는 예외로 올려 응답을 막는다."""
    logger = request.app.state.access_log
    if logger is None:
        return
    actor = actor or getattr(request.state, "actor", None)
    logger.record(actor_id=actor.staff_id if actor else None, actor_label=actor.label if actor else "anonymous",
                  client_ip=client_ip(request), action=action, target_type=target_type, subjects=subjects,
                  detail_count=count, outcome=outcome)


def require(request: Request, permission: str) -> Actor:
    actor = current_actor(request)
    if not actor.can(permission):
        audit(request, "DENIED", permission, outcome="DENIED")
        raise UserError("이 업무를 할 권한이 없습니다. 개인정보 책임자에게 문의해 주세요.", 403)
    return actor


def check_csrf(request: Request, token: str) -> None:
    actor = current_actor(request)
    if not secrets.compare_digest(token.encode("utf-8"), actor.csrf_token.encode("utf-8")):
        raise UserError("화면을 새로 열고 다시 입력해 주세요.", 403)


def same_origin(request: Request) -> bool:
    origin = request.headers.get("origin")
    if not origin or origin == "null":
        return origin is None
    return origin == f"{request.url.scheme}://{request.headers.get('host', '')}"


def render(request: Request, name: str, context: dict, status_code: int = 200):
    actor = getattr(request.state, "actor", None)
    context.setdefault("today", None)
    context.update(csrf_token=actor.csrf_token if actor else "", actor=actor,
                   auth_enabled=request.app.state.auth is not None)
    return request.app.state.templates.TemplateResponse(
        request=request, name=name, context=context, status_code=status_code)
