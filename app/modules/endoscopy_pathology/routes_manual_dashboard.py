"""HTTP 입력을 검증하고 모든 업무 변경을 서비스에 위임한다. DB·파일에 직접 접근하지 않는다."""

import secrets
from typing import Annotated
from urllib.parse import urlencode
from uuid import UUID

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from .manual_dashboard import DashboardError, ManualDashboardService, form_date


router = APIRouter()
NOTICES = {
    "registered": "새 검사를 접수했습니다.",
    "handoff": "인계를 기록했습니다.",
    "bulk": "선택한 건에 원장 지시를 기록했습니다.",
    "imported": "가져오기를 마쳤습니다. 신규 행만 저장했습니다.",
    "exported": "지정 폴더에 엑셀을 저장했습니다.",
}


def service(request: Request) -> ManualDashboardService:
    return request.app.state.dashboard_service


def check_csrf(request: Request, csrf_token: Annotated[str, Form()] = "") -> None:
    if not secrets.compare_digest(csrf_token.encode("utf-8"), request.app.state.csrf_token.encode("utf-8")):
        raise DashboardError("화면을 새로 열고 다시 입력해 주세요.", 403)


Service = Annotated[ManualDashboardService, Depends(service)]
Csrf = Depends(check_csrf)


def redirect(path: str = "/dashboard", **params) -> RedirectResponse:
    query = urlencode({k: v for k, v in params.items() if v not in (None, "")})
    return RedirectResponse(f"{path}?{query}" if query else path, status_code=303)


def render(request: Request, name: str, context: dict, status_code: int = 200):
    context["csrf_token"] = request.app.state.csrf_token
    return request.app.state.templates.TemplateResponse(
        request=request, name=name, context=context, status_code=status_code)


@router.get("/")
def home():
    return RedirectResponse("/dashboard", status_code=303)


@router.get("/dashboard")
def dashboard(request: Request, service: Service, stage: str = "ALL", kind: str = "ALL",
              selected_id: UUID | None = None, q: str = "", page: int = 1, new: bool = False, notice: str = ""):
    context = service.snapshot(stage=stage, selected_id=selected_id, query=q, kind=kind, page=page)
    context.update(new=new, notice=NOTICES.get(notice, ""))
    return render(request, "manual_dashboard.html", context)


@router.post("/ledger/register", dependencies=[Csrf])
def register(service: Service, kind: Annotated[str, Form()] = "", chart_no: Annotated[str, Form()] = "",
             patient_name: Annotated[str, Form()] = "", exam_date: Annotated[str, Form()] = "",
             sex: Annotated[str, Form()] = "", age: Annotated[str, Form()] = "",
             procedure_type: Annotated[str, Form()] = "", specimen_count: Annotated[str, Form()] = "",
             site: Annotated[str, Form()] = ""):
    entry_id = service.register(kind, chart_no, patient_name, form_date(exam_date), sex, age.strip(),
                                procedure_type, specimen_count.strip(), site)
    return redirect(selected_id=entry_id, notice="registered")


@router.post("/ledger/handoff", dependencies=[Csrf])
def handoff(service: Service, registered_by: Annotated[str, Form()] = "",
            handed_by: Annotated[str, Form()] = "", receiver_name: Annotated[str, Form()] = "",
            confirmed_count: Annotated[str, Form()] = ""):
    if not confirmed_count.isdigit() or len(confirmed_count) > 3:
        raise DashboardError("확인한 병 수를 숫자로 입력해 주세요.", 422)
    service.handoff(registered_by, handed_by, receiver_name, int(confirmed_count))
    return redirect(stage="RESULT_PENDING", notice="handoff")


@router.post("/ledger/cases/{entry_id}/receive", dependencies=[Csrf])
def receive(entry_id: UUID, service: Service, report_ref: Annotated[str, Form()] = "",
            result_notation: Annotated[str, Form()] = "", site_summary: Annotated[str, Form()] = "",
            sydney_notation: Annotated[str, Form()] = ""):
    service.receive(entry_id, report_ref, result_notation, site_summary, sydney_notation)
    return redirect(selected_id=entry_id)


@router.post("/ledger/cases/{entry_id}/decide", dependencies=[Csrf])
def decide(entry_id: UUID, service: Service, mode: Annotated[str, Form()] = "",
           due_date: Annotated[str, Form()] = "", reason: Annotated[str, Form()] = ""):
    service.decide(entry_id, mode, form_date(due_date), reason)
    return redirect(selected_id=entry_id)


@router.post("/ledger/bulk-decide", dependencies=[Csrf])
def bulk_decide(service: Service, entry_ids: Annotated[list[UUID], Form()] = (),
                reason: Annotated[str, Form()] = ""):
    service.bulk_not_required(list(entry_ids), reason)
    return redirect(stage="DOCTOR_PENDING", notice="bulk")


@router.post("/ledger/cases/{entry_id}/followup-done", dependencies=[Csrf])
def followup_done(entry_id: UUID, service: Service, done_on: Annotated[str, Form()] = ""):
    service.complete_followup(entry_id, form_date(done_on))
    return redirect(selected_id=entry_id)


@router.get("/ledger/excel")
def excel_page(request: Request, service: Service, token: str = "", notice: str = ""):
    context = service.snapshot()
    context.update(token=token, preview=service.preview(token) if token else None,
                   notice=NOTICES.get(notice, ""), max_upload_mb=service.max_upload_bytes // (1024 * 1024))
    return render(request, "ledger_excel.html", context)


@router.post("/ledger/import/preview")
async def import_preview(request: Request, service: Service):
    # 크기 제한을 넘는 요청은 본문을 읽기 전에 거절한다. 파일은 메모리에서만 다룬다.
    length = request.headers.get("content-length", "")
    if not length.isdigit() or int(length) > service.max_upload_bytes + 64 * 1024:
        raise DashboardError("파일이 너무 큽니다. 5MB 이하로 올려 주세요.", 413)
    form = await request.form(max_files=1, max_fields=5)
    try:
        check_csrf(request, str(form.get("csrf_token", "")))
        upload = form.get("ledger_file")
        if upload is None or isinstance(upload, str):
            raise DashboardError("엑셀 파일을 선택해 주세요.", 422)
        data = await upload.read()
    finally:
        await form.close()
    token = service.preview_import(data)
    return redirect("/ledger/excel", token=token)


@router.post("/ledger/import/commit", dependencies=[Csrf])
def import_commit(service: Service, token: Annotated[str, Form()] = ""):
    service.commit_import(token)
    return redirect("/ledger/excel", notice="imported")


@router.post("/ledger/export", dependencies=[Csrf])
def export(service: Service):
    service.export()
    return redirect("/ledger/excel", notice="exported")


@router.post("/ledger/reset", dependencies=[Csrf])
def reset(service: Service):
    service.reset()
    return RedirectResponse("/dashboard", status_code=303)
