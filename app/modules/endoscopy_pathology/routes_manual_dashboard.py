"""시연 HTTP 입력을 검증하고 모든 업무 변경을 서비스에 위임한다."""

from datetime import date
import re
import secrets
from typing import Annotated
from urllib.parse import urlencode
from uuid import UUID

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from .manual_dashboard import STAGE_LABELS, DashboardError, ManualDashboardService


router = APIRouter()
ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def service(request: Request) -> ManualDashboardService:
    return request.app.state.dashboard_service


def check_csrf(request: Request, csrf_token: Annotated[str, Form()] = "") -> None:
    if not secrets.compare_digest(csrf_token.encode("utf-8"), request.app.state.csrf_token.encode("utf-8")):
        raise DashboardError("화면을 새로 열고 다시 입력해 주세요.", 403)


Service = Annotated[ManualDashboardService, Depends(service)]
Csrf = Depends(check_csrf)
# 입력 후에도 보던 업무 분류로 돌아간다. 알 수 없는 값은 전체 보기로 되돌린다.
ReturnStage = Annotated[str, Form(alias="stage")]


def case_redirect(case_id: UUID, stage: str = "ALL") -> RedirectResponse:
    query = {"stage": stage} if stage in STAGE_LABELS else {}
    query["selected_id"] = str(case_id)
    return RedirectResponse(f"/dashboard?{urlencode(query)}", status_code=303)


@router.get("/")
def home():
    return RedirectResponse("/dashboard", status_code=303)


@router.get("/dashboard")
def dashboard(request: Request, service: Service, stage: str = "ALL", selected_id: UUID | None = None):
    context = service.snapshot(stage=stage, selected_id=selected_id)
    context["csrf_token"] = request.app.state.csrf_token
    return request.app.state.templates.TemplateResponse(
        request=request, name="manual_dashboard.html", context=context,
    )


@router.post("/demo/cases/{case_id}/receive", dependencies=[Csrf])
def receive(case_id: UUID, service: Service,
            result_summary: Annotated[str, Form()] = "",
            site_summary: Annotated[str, Form()] = "",
            return_stage: ReturnStage = "ALL"):
    service.receive(case_id, result_summary, site_summary)
    return case_redirect(case_id, return_stage)


@router.post("/demo/cases/{case_id}/decide", dependencies=[Csrf])
def decide(case_id: UUID, service: Service, mode: Annotated[str, Form()] = "",
           due_date: Annotated[str, Form()] = "", reason: Annotated[str, Form()] = "",
           return_stage: ReturnStage = "ALL"):
    # fromisoformat은 20300115·2030-W03-2도 받으므로 브라우저 date 입력 형식만 허용한다.
    if due_date and not ISO_DATE.fullmatch(due_date):
        raise DashboardError("날짜 형식을 확인해 주세요.", 422)
    try:
        parsed_date = date.fromisoformat(due_date) if due_date else None
    except ValueError:
        raise DashboardError("날짜 형식을 확인해 주세요.", 422) from None
    service.decide(case_id, mode, parsed_date, reason)
    return case_redirect(case_id, return_stage)


@router.post("/demo/cases/{case_id}/notify", dependencies=[Csrf])
def notify(case_id: UUID, service: Service, outcome: Annotated[str, Form()] = "",
           return_stage: ReturnStage = "ALL"):
    service.notify(case_id, outcome)
    return case_redirect(case_id, return_stage)


@router.post("/demo/reset", dependencies=[Csrf])
def reset(service: Service):
    service.reset()
    return RedirectResponse("/dashboard", status_code=303)
