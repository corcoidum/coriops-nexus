"""시연 HTTP 입력을 검증하고 모든 업무 변경을 서비스에 위임한다."""

from datetime import date
import secrets
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from .manual_dashboard import DashboardError, ManualDashboardService


router = APIRouter()


def service(request: Request) -> ManualDashboardService:
    return request.app.state.dashboard_service


def check_csrf(request: Request, csrf_token: Annotated[str, Form()] = "") -> None:
    if not secrets.compare_digest(csrf_token.encode("utf-8"), request.app.state.csrf_token.encode("utf-8")):
        raise DashboardError("화면을 새로 열고 다시 입력해 주세요.", 403)


Service = Annotated[ManualDashboardService, Depends(service)]
Csrf = Depends(check_csrf)


def case_redirect(case_id: UUID) -> RedirectResponse:
    return RedirectResponse(f"/dashboard?selected_id={case_id}", status_code=303)


def parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        raise DashboardError("날짜 형식을 확인해 주세요.", 422) from None


@router.get("/")
def home():
    return RedirectResponse("/dashboard", status_code=303)


@router.get("/dashboard")
def dashboard(request: Request, service: Service, stage: str = "ALL",
              selected_id: UUID | None = None, q: str = ""):
    context = service.snapshot(stage=stage, selected_id=selected_id, query=q)
    context["csrf_token"] = request.app.state.csrf_token
    return request.app.state.templates.TemplateResponse(
        request=request, name="manual_dashboard.html", context=context,
    )


@router.post("/demo/handoff", dependencies=[Csrf])
def handoff(service: Service, registered_by: Annotated[str, Form()] = "",
            handed_by: Annotated[str, Form()] = "", receiver_name: Annotated[str, Form()] = "",
            confirmed_count: Annotated[str, Form()] = ""):
    if not confirmed_count.isdigit() or len(confirmed_count) > 3:
        raise DashboardError("확인한 병 수를 숫자로 입력해 주세요.", 422)
    service.handoff(registered_by, handed_by, receiver_name, int(confirmed_count))
    return RedirectResponse("/dashboard?stage=RESULT_PENDING", status_code=303)


@router.post("/demo/cases/{case_id}/receive", dependencies=[Csrf])
def receive(case_id: UUID, service: Service,
            report_ref: Annotated[str, Form()] = "",
            result_notation: Annotated[str, Form()] = "",
            site_summary: Annotated[str, Form()] = "",
            sydney_notation: Annotated[str, Form()] = ""):
    service.receive(case_id, report_ref, result_notation, site_summary, sydney_notation)
    return case_redirect(case_id)


@router.post("/demo/cases/{case_id}/decide", dependencies=[Csrf])
def decide(case_id: UUID, service: Service, mode: Annotated[str, Form()] = "",
           due_date: Annotated[str, Form()] = "", reason: Annotated[str, Form()] = ""):
    service.decide(case_id, mode, parse_date(due_date), reason)
    return case_redirect(case_id)


@router.post("/demo/cases/{case_id}/followup-done", dependencies=[Csrf])
def followup_done(case_id: UUID, service: Service, done_on: Annotated[str, Form()] = ""):
    service.complete_followup(case_id, parse_date(done_on))
    return case_redirect(case_id)


@router.post("/demo/reset", dependencies=[Csrf])
def reset(service: Service):
    service.reset()
    return RedirectResponse("/dashboard", status_code=303)
