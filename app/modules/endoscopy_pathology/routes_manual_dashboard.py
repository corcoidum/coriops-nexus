"""HTTP 입력을 검증하고 업무 변경을 서비스에 위임한다. DB·파일에 직접 접근하지 않는다.

모든 화면은 권한(require)을 확인하고, 환자 정보를 보여주거나 바꾸면 접속기록(audit)을 남긴다.
목록은 LIST(이름 가림), 상세는 VIEW(전체 이름), 변경은 CREATE/UPDATE로 차트번호마다 한 행씩 기록한다.
"""

from typing import Annotated
from urllib.parse import urlencode
from uuid import UUID

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from app.kernel.web import audit, check_csrf, render, require

from .ledger_model import KINDS, STAGE_LABELS
from .manual_dashboard import DashboardError, ManualDashboardService, form_date


router = APIRouter()
NOTICES = {
    "registered": "새 검사를 접수했습니다.",
    "handoff": "인계를 기록했습니다.",
    "bulk": "선택한 건에 원장 지시를 기록했습니다.",
    "imported": "가져오기를 마쳤습니다. 신규 행만 저장했습니다.",
    "exported": "지정 폴더에 엑셀을 저장했습니다.",
    "followups_exported": "재검 대상자 목록을 지정 폴더에 저장했습니다.",
}


def service(request: Request) -> ManualDashboardService:
    return request.app.state.dashboard_service


def csrf(request: Request, csrf_token: Annotated[str, Form()] = "") -> None:
    check_csrf(request, csrf_token)


Service = Annotated[ManualDashboardService, Depends(service)]
Csrf = Depends(csrf)


def redirect(path: str = "/dashboard", **params) -> RedirectResponse:
    query = urlencode({k: v for k, v in params.items() if v not in (None, "")})
    return RedirectResponse(f"{path}?{query}" if query else path, status_code=303)


# 처리 후에도 보던 단계·종류 목록으로 돌아간다. 알 수 없는 값은 전체 보기로 되돌린다.
ReturnStage = Annotated[str, Form(alias="stage")]
ReturnKind = Annotated[str, Form(alias="kind")]


def case_redirect(service: ManualDashboardService, entry_id: UUID, stage: str, kind: str) -> RedirectResponse:
    stage = stage if stage in STAGE_LABELS else ""
    kind = kind if kind in KINDS else ""
    # 다음 단계로 넘어간 항목은 보던 단계의 목록·상세와 어긋나므로 선택하지 않는다.
    keep = not stage or service.stage_of(entry_id) == stage
    return redirect(stage=stage, kind=kind, selected_id=entry_id if keep else None)


@router.get("/")
def home():
    return RedirectResponse("/dashboard", status_code=303)


@router.get("/dashboard")
def dashboard(request: Request, service: Service, stage: str = "ALL", kind: str = "ALL",
              selected_id: UUID | None = None, q: str = "", page: int = 1, new: bool = False, notice: str = "",
              due: str = "", due_from: str = "", due_to: str = ""):
    actor = require(request, "ledger.view")
    context = service.snapshot(stage=stage, selected_id=selected_id, query=q, kind=kind, page=page, due=due,
                               due_from=form_date(due_from), due_to=form_date(due_to))
    context.update(new=new, notice=NOTICES.get(notice, ""), can_export=actor.can("excel.export"))
    # 화면에 나가기 전에 기록한다. 기록이 실패하면 화면도 나가지 않는다.
    audit(request, "LIST", "ledger_list", subjects=[c.chart_no for c in context["cases"]])
    if context["selected"] is not None and not new:
        audit(request, "VIEW", "ledger_entry", subjects=[context["selected"].chart_no])
    return render(request, "manual_dashboard.html", context)


@router.post("/ledger/register", dependencies=[Csrf])
def register(request: Request, service: Service, kind: Annotated[str, Form()] = "",
             chart_no: Annotated[str, Form()] = "", patient_name: Annotated[str, Form()] = "",
             exam_date: Annotated[str, Form()] = "", sex: Annotated[str, Form()] = "",
             age: Annotated[str, Form()] = "", procedure_type: Annotated[str, Form()] = "",
             specimen_count: Annotated[str, Form()] = "", site: Annotated[str, Form()] = ""):
    require(request, "ledger.register")
    entry_id = service.register(kind, chart_no, patient_name, form_date(exam_date), sex, age.strip(),
                                procedure_type, specimen_count.strip(), site)
    audit(request, "CREATE", "ledger_entry", subjects=[service.subject_of(entry_id)])
    return redirect(selected_id=entry_id, notice="registered")


@router.post("/ledger/handoff", dependencies=[Csrf])
def handoff(request: Request, service: Service, registered_by: Annotated[str, Form()] = "",
            handed_by: Annotated[str, Form()] = "", receiver_name: Annotated[str, Form()] = "",
            confirmed_count: Annotated[str, Form()] = ""):
    require(request, "ledger.handoff")
    if not confirmed_count.isdigit() or len(confirmed_count) > 3:
        raise DashboardError("확인한 병 수를 숫자로 입력해 주세요.", 422)
    subjects = service.pending_handoff_subjects()
    service.handoff(registered_by, handed_by, receiver_name, int(confirmed_count))
    audit(request, "UPDATE", "ledger_handoff", subjects=subjects)
    return redirect(stage="RESULT_PENDING", notice="handoff")


@router.post("/ledger/cases/{entry_id}/receive", dependencies=[Csrf])
def receive(request: Request, entry_id: UUID, service: Service, report_ref: Annotated[str, Form()] = "",
            result_notation: Annotated[str, Form()] = "", site_summary: Annotated[str, Form()] = "",
            sydney_notation: Annotated[str, Form()] = "",
            return_stage: ReturnStage = "", return_kind: ReturnKind = ""):
    require(request, "ledger.result")
    service.receive(entry_id, report_ref, result_notation, site_summary, sydney_notation)
    audit(request, "UPDATE", "ledger_result", subjects=[service.subject_of(entry_id)])
    return case_redirect(service, entry_id, return_stage, return_kind)


@router.post("/ledger/cases/{entry_id}/decide", dependencies=[Csrf])
def decide(request: Request, entry_id: UUID, service: Service, mode: Annotated[str, Form()] = "",
           due_date: Annotated[str, Form()] = "", reason: Annotated[str, Form()] = "",
           return_stage: ReturnStage = "", return_kind: ReturnKind = ""):
    require(request, "ledger.decide")
    service.decide(entry_id, mode, form_date(due_date), reason)
    audit(request, "UPDATE", "ledger_decision", subjects=[service.subject_of(entry_id)])
    return case_redirect(service, entry_id, return_stage, return_kind)


@router.post("/ledger/bulk-decide", dependencies=[Csrf])
def bulk_decide(request: Request, service: Service, entry_ids: Annotated[list[UUID], Form()] = (),
                reason: Annotated[str, Form()] = ""):
    require(request, "ledger.decide")
    count = service.bulk_not_required(list(entry_ids), reason)
    audit(request, "UPDATE", "ledger_decision_bulk", subjects=service.subjects_of(list(entry_ids)), count=count)
    return redirect(stage="DOCTOR_PENDING", notice="bulk")


@router.post("/ledger/cases/{entry_id}/followup-done", dependencies=[Csrf])
def followup_done(request: Request, entry_id: UUID, service: Service, done_on: Annotated[str, Form()] = "",
                  return_stage: ReturnStage = "", return_kind: ReturnKind = ""):
    require(request, "ledger.followup")
    service.complete_followup(entry_id, form_date(done_on))
    audit(request, "UPDATE", "ledger_followup", subjects=[service.subject_of(entry_id)])
    return case_redirect(service, entry_id, return_stage, return_kind)


@router.get("/ledger/excel")
def excel_page(request: Request, service: Service, token: str = "", notice: str = ""):
    actor = require(request, "ledger.view")
    context = service.snapshot()
    preview = None
    if token:
        require(request, "excel.import")
        preview = service.preview(token)
        shown = [d["entry"].chart_no for d in preview["differences"]] + [m["entry"].chart_no for m in preview["missing"]]
        audit(request, "LIST", "excel_reconcile", subjects=shown)
    context.update(token=token, preview=preview, notice=NOTICES.get(notice, ""),
                   can_import=actor.can("excel.import"), can_export=actor.can("excel.export"),
                   max_upload_mb=service.max_upload_bytes // (1024 * 1024))
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
        require(request, "excel.import")
        upload = form.get("ledger_file")
        if upload is None or isinstance(upload, str):
            raise DashboardError("엑셀 파일을 선택해 주세요.", 422)
        data = await upload.read()
    finally:
        await form.close()
    token = service.preview_import(data)
    audit(request, "IMPORT", "excel_preview", count=service.preview(token)["new_total"], outcome="PREVIEW")
    return redirect("/ledger/excel", token=token)


@router.post("/ledger/import/commit", dependencies=[Csrf])
def import_commit(request: Request, service: Service, token: Annotated[str, Form()] = ""):
    require(request, "excel.import")
    subjects = service.import_subjects(token)
    count = service.commit_import(token)
    audit(request, "IMPORT", "excel_commit", subjects=subjects, count=count)
    return redirect("/ledger/excel", notice="imported")


@router.post("/ledger/export", dependencies=[Csrf])
def export(request: Request, service: Service):
    require(request, "excel.export")
    record = service.export()
    # 출력은 한 행: 건수와 함께 남기고, 파일명·시각은 출력 기록(ledger_exports)에 있다.
    audit(request, "EXPORT", "excel_export", count=record.row_count)
    return redirect("/ledger/excel", notice="exported")


@router.post("/ledger/export/followups", dependencies=[Csrf])
def export_followups(request: Request, service: Service, kind: Annotated[str, Form()] = "ALL",
                     q: Annotated[str, Form()] = "", due: Annotated[str, Form()] = "",
                     due_from: Annotated[str, Form()] = "", due_to: Annotated[str, Form()] = ""):
    require(request, "excel.export")
    record, subjects = service.export_followups(kind, q, due, form_date(due_from), form_date(due_to))
    # 대상자 목록은 이름이 그대로 들어가므로 환자별로 기록한다.
    audit(request, "EXPORT", "followup_list", subjects=subjects, count=record.row_count)
    return redirect(stage="FOLLOWUP", kind=kind, q=q, due=due, due_from=due_from, due_to=due_to,
                    notice="followups_exported")


@router.post("/ledger/reset", dependencies=[Csrf])
def reset(service: Service):
    service.reset()
    return RedirectResponse("/dashboard", status_code=303)
