"""혈액검체 탭의 HTTP 입력을 검증하고 업무 변경을 서비스에 위임한다.

합성 메모리 시연에서만 조립된다(app/main.py). 권한·접속기록은 조직검체 장부와 같은 방식을 따른다.
"""

from datetime import date
from itertools import zip_longest
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from app.kernel.web import UserError, audit, check_csrf, render, require

from .dashboard import LabDashboardService


router = APIRouter()


def service(request: Request) -> LabDashboardService:
    return request.app.state.lab_service


def csrf(request: Request, csrf_token: Annotated[str, Form()] = "") -> None:
    check_csrf(request, csrf_token)


Service = Annotated[LabDashboardService, Depends(service)]
Csrf = Depends(csrf)


def case_redirect(case_id: UUID) -> RedirectResponse:
    return RedirectResponse(f"/lab?selected_id={case_id}", status_code=303)


@router.get("/lab")
def lab_dashboard(request: Request, service: Service, stage: str = "ALL", selected_id: UUID | None = None):
    require(request, "ledger.view")
    context = service.snapshot(stage=stage, selected_id=selected_id)
    audit(request, "LIST", "lab_list", subjects=[case.record.chart_no for case in context["cases"]])
    if context["selected"] is not None:
        audit(request, "VIEW", "lab_entry", subjects=[context["selected"].record.chart_no])
    return render(request, "lab_dashboard.html", context)


def form_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        raise UserError("날짜 형식을 확인해 주세요.", 422) from None


@router.post("/lab/cases/{case_id}/result", dependencies=[Csrf])
def enter_result(request: Request, case_id: UUID, service: Service,
                 report_ref: Annotated[str, Form()] = "", report_date: Annotated[str, Form()] = "",
                 item_name: Annotated[list[str], Form()] = (), item_value: Annotated[list[str], Form()] = (),
                 item_flag: Annotated[list[str], Form()] = (), qual_name: Annotated[list[str], Form()] = (),
                 qual_value: Annotated[list[str], Form()] = (), no_flagged: Annotated[str, Form()] = "",
                 entered_by: Annotated[str, Form()] = ""):
    require(request, "ledger.result")
    rows = [(name or "", value or "", flag or "") for name, value, flag in zip_longest(item_name, item_value, item_flag)]
    service.enter_result(case_id, report_ref=report_ref, report_date=form_date(report_date), rows=rows,
                         qualitative=dict(zip(qual_name, qual_value)), no_flagged=no_flagged == "1",
                         entered_by=entered_by)
    audit(request, "UPDATE", "lab_result", subjects=[service.subject_of(case_id)])
    return case_redirect(case_id)


@router.post("/lab/cases/{case_id}/mark-critical", dependencies=[Csrf])
def mark_critical(request: Request, case_id: UUID, service: Service,
                  critical_items: Annotated[list[str], Form()] = (), marked_by: Annotated[str, Form()] = ""):
    require(request, "lab.critical_mark")
    service.mark_critical(case_id, list(critical_items), marked_by)
    audit(request, "UPDATE", "lab_critical_mark", subjects=[service.subject_of(case_id)])
    return case_redirect(case_id)


@router.post("/lab/cases/{case_id}/report-critical", dependencies=[Csrf])
def report_critical(request: Request, case_id: UUID, service: Service,
                    reported_by: Annotated[str, Form()] = ""):
    require(request, "ledger.result")
    service.report_critical(case_id, reported_by)
    audit(request, "UPDATE", "lab_critical_report", subjects=[service.subject_of(case_id)])
    return case_redirect(case_id)


@router.post("/lab/cases/{case_id}/check", dependencies=[Csrf])
def check(request: Request, case_id: UUID, service: Service, checked_by: Annotated[str, Form()] = "",
          followup_note: Annotated[str, Form()] = ""):
    require(request, "ledger.result")
    service.check(case_id, checked_by, followup_note)
    audit(request, "UPDATE", "lab_check", subjects=[service.subject_of(case_id)])
    return case_redirect(case_id)


@router.post("/lab/reset", dependencies=[Csrf])
def reset(service: Service):
    service.reset()
    return RedirectResponse("/lab", status_code=303)
