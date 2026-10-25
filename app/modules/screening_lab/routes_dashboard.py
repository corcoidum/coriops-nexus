"""혈액검체 탭의 HTTP 입력을 검증하고 업무 변경을 서비스에 위임한다.

합성 메모리 시연에서만 조립된다(app/main.py). 권한·접속기록은 조직검체 장부와 같은 방식을 따른다.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from app.kernel.web import audit, check_csrf, render, require

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


@router.post("/lab/cases/{case_id}/report-critical", dependencies=[Csrf])
def report_critical(request: Request, case_id: UUID, service: Service,
                    reported_by: Annotated[str, Form()] = ""):
    require(request, "ledger.result")
    service.report_critical(case_id, reported_by)
    audit(request, "UPDATE", "lab_critical_report", subjects=[service.subject_of(case_id)])
    return case_redirect(case_id)


@router.post("/lab/cases/{case_id}/check", dependencies=[Csrf])
def check(request: Request, case_id: UUID, service: Service, checked_by: Annotated[str, Form()] = ""):
    require(request, "ledger.result")
    service.check(case_id, checked_by)
    audit(request, "UPDATE", "lab_check", subjects=[service.subject_of(case_id)])
    return case_redirect(case_id)


@router.post("/lab/reset", dependencies=[Csrf])
def reset(service: Service):
    service.reset()
    return RedirectResponse("/lab", status_code=303)
