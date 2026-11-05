"""PDF 업로드는 대조 미리보기와 직원 확정 저장을 분리한다."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse

from app.kernel.web import audit, render, require

from .routes_dashboard import Csrf, Service, case_redirect
from .dashboard import KST


router = APIRouter()


@router.get("/lab/pdf/{case_id}")
def upload(request: Request, service: Service, case_id: UUID):
    require(request, "ledger.result")
    case = service.case(case_id)
    audit(request, "VIEW", "lab_pdf_upload", subjects=[case.record.chart_no])
    return render(request, "lab_pdf.html", {"case": case, "preview": None, "today": service.now().astimezone(KST).date()})


@router.post("/lab/pdf/preview/{case_id}", dependencies=[Csrf])
async def preview_pdf(request: Request, service: Service, case_id: UUID, file: Annotated[UploadFile, File()]):
    actor = require(request, "ledger.result")
    assist = request.app.state.pdf_assist
    try:
        data = await file.read(assist.limits["maximum_upload_bytes"] + 1)
    finally:
        await file.close()
    # 추출은 CPU 작업이므로 비동기 요청 루프를 막지 않는다.
    from starlette.concurrency import run_in_threadpool
    token = await run_in_threadpool(assist.create, actor, case_id, data)
    audit(request, "IMPORT", "lab_pdf_preview", subjects=[service.subject_of(case_id)])
    return RedirectResponse(f"/lab/pdf/preview/{token}", 303)


@router.get("/lab/pdf/preview/{token}")
def show_preview(request: Request, service: Service, token: str):
    actor = require(request, "ledger.result")
    preview = request.app.state.pdf_assist.get(token, actor)
    case = service.case(preview.case_id)
    audit(request, "VIEW", "lab_pdf_preview", subjects=[case.record.chart_no])
    return render(request, "lab_pdf.html", {"case": case, "preview": preview, "token": token,
                                            "today": service.now().astimezone(KST).date()})


@router.post("/lab/pdf/commit/{token}", dependencies=[Csrf])
def commit(request: Request, service: Service, token: str, acknowledged: Annotated[str, Form()] = "",
           no_flagged: Annotated[str, Form()] = ""):
    actor = require(request, "ledger.result")
    with request.app.state.pdf_assist.confirmed(token, actor, acknowledged == "1", no_flagged == "1") as preview:
        with service.transaction():
            parsed = preview.parsed
            service.enter_result(preview.case_id, report_ref=parsed.identity["report_ref"],
                                 report_date=parsed.report_date, rows=list(parsed.rows),
                                 qualitative=parsed.qualitative, no_flagged=not parsed.rows,
                                 entered_by=actor.label)
            audit(request, "IMPORT", "lab_pdf_commit", subjects=[service.subject_of(preview.case_id)])
    return case_redirect(preview.case_id)
