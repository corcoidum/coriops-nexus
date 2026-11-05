"""혈액검체 탭의 HTTP 입력을 검증하고 업무 변경을 서비스에 위임한다.

시연·DB 모드에 조립된다(app/main.py). 권한·접속기록은 공통 경계를 사용한다.
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
def lab_dashboard(request: Request, service: Service, stage: str = "ALL", selected_id: UUID | None = None,
                  new: bool = False):
    if stage == "CRITICAL_PENDING":
        suffix = f"?selected_id={selected_id}" if selected_id else ""
        return RedirectResponse(f"/critical{suffix}", status_code=303)
    return dashboard_page(request, service, stage, selected_id, new=new)


@router.get("/critical")
def critical_dashboard(request: Request, service: Service, selected_id: UUID | None = None,
                       notice: str = ""):
    return dashboard_page(request, service, "CRITICAL_PENDING", selected_id, critical_view=True,
                          notice="원장 보고 완료를 기록했습니다." if notice == "reported" else "")


def dashboard_page(request: Request, service: LabDashboardService, stage: str,
                   selected_id: UUID | None, *, critical_view: bool = False, notice: str = "", new: bool = False):
    require(request, "ledger.view")
    context = service.snapshot(stage=stage, selected_id=selected_id)
    if critical_view and context["selected"] and context["selected"].stage != "CRITICAL_PENDING":
        raise UserError("원장 보고 대기 항목이 아닙니다. 위급치 보고 목록에서 다시 선택해 주세요.", 422)
    context.update(critical_view=critical_view, notice=notice, new=new)
    audit(request, "LIST", "lab_list", subjects=[case.record.chart_no for case in context["cases"]])
    if context["selected"] is not None and not new:
        audit(request, "VIEW", "lab_entry", subjects=[context["selected"].record.chart_no])
    return render(request, "lab_dashboard.html", context)


@router.get("/lab/paper")
def lab_paper(request: Request, service: Service, start: str = "", end: str = ""):
    require(request, "ledger.view")
    context = service.paper_snapshot(form_date(start), form_date(end))
    audit(request, "LIST", "lab_paper", subjects=[case.record.chart_no for case in context["cases"]])
    return render(request, "lab_paper.html", context)


def form_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        raise UserError("날짜 형식을 확인해 주세요.", 422) from None


@router.post("/lab/cases", dependencies=[Csrf])
def register(request: Request, service: Service, chart_no: Annotated[str, Form()] = "",
             patient_name: Annotated[str, Form()] = "", received_date: Annotated[str, Form()] = "",
             exam_kinds: Annotated[list[str], Form()] = (), sex: Annotated[str, Form()] = "",
             age: Annotated[str, Form()] = "", intake_id: Annotated[UUID | None, Form()] = None):
    actor = require(request, "ledger.register")
    with service.transaction():
        case_id = service.register(chart_no=chart_no, patient_name=patient_name, received_date=form_date(received_date),
                                   exam_kinds=list(exam_kinds), sex=sex, age=age, intake_id=intake_id,
                                   registered_by=actor.label)
        audit(request, "CREATE", "lab_entry", subjects=[service.subject_of(case_id)])
    return case_redirect(case_id)


@router.post("/lab/cases/{case_id}/result", dependencies=[Csrf])
def enter_result(request: Request, case_id: UUID, service: Service,
                 report_ref: Annotated[str, Form()] = "", report_date: Annotated[str, Form()] = "",
                 item_name: Annotated[list[str], Form()] = (), item_value: Annotated[list[str], Form()] = (),
                 item_flag: Annotated[list[str], Form()] = (), qual_name: Annotated[list[str], Form()] = (),
                 qual_value: Annotated[list[str], Form()] = (), no_flagged: Annotated[str, Form()] = "",
                 entered_by: Annotated[str, Form()] = ""):
    actor = require(request, "ledger.result")
    rows = [(name or "", value or "", flag or "") for name, value, flag in zip_longest(item_name, item_value, item_flag)]
    with service.transaction():
        service.enter_result(case_id, report_ref=report_ref, report_date=form_date(report_date), rows=rows,
                             qualitative=dict(zip(qual_name, qual_value)), no_flagged=no_flagged == "1",
                             entered_by=actor.label if service.persistent else entered_by)
        audit(request, "UPDATE", "lab_result", subjects=[service.subject_of(case_id)])
    return case_redirect(case_id)


@router.post("/lab/cases/{case_id}/mark-critical", dependencies=[Csrf])
def mark_critical(request: Request, case_id: UUID, service: Service,
                  critical_items: Annotated[list[str], Form()] = (), marked_by: Annotated[str, Form()] = ""):
    actor = require(request, "lab.critical_mark")
    with service.transaction():
        service.mark_critical(case_id, list(critical_items), actor.label if service.persistent else marked_by)
        audit(request, "UPDATE", "lab_critical_mark", subjects=[service.subject_of(case_id)])
    return case_redirect(case_id)


@router.post("/lab/cases/{case_id}/report-critical", dependencies=[Csrf])
def report_critical(request: Request, case_id: UUID, service: Service,
                    reported_by: Annotated[str, Form()] = "", back: Annotated[str, Form()] = ""):
    actor = require(request, "ledger.result")
    with service.transaction():
        service.report_critical(case_id, actor.label if service.persistent else reported_by)
        audit(request, "UPDATE", "lab_critical_report", subjects=[service.subject_of(case_id)])
    if back == "critical":
        return RedirectResponse("/critical?notice=reported", status_code=303)
    return case_redirect(case_id)


@router.post("/lab/cases/{case_id}/check", dependencies=[Csrf])
def check(request: Request, case_id: UUID, service: Service, checked_by: Annotated[str, Form()] = "",
          followup_note: Annotated[str, Form()] = ""):
    actor = require(request, "ledger.result")
    with service.transaction():
        service.check(case_id, actor.label if service.persistent else checked_by, followup_note)
        audit(request, "UPDATE", "lab_check", subjects=[service.subject_of(case_id)])
    return case_redirect(case_id)


@router.post("/lab/reset", dependencies=[Csrf])
def reset(service: Service):
    service.reset()
    return RedirectResponse("/lab", status_code=303)
