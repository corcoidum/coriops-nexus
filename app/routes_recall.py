"""공통 Recall 조회. 완료·일정 변경은 권한이 적용된 원본 업무에서 기록한다."""

from datetime import date

from fastapi import APIRouter, Request

from app.kernel.web import UserError, audit, render, require


router = APIRouter()


@router.get("/recalls")
def recalls(request: Request, kind: str = "ALL", bucket: str = "due", start: str = "", end: str = ""):
    require(request, "ledger.view")
    try:
        first, last = (date.fromisoformat(value) if value else None for value in (start, end))
    except ValueError:
        raise UserError("조회 날짜를 확인해 주세요.", 422) from None
    context = request.app.state.recalls.snapshot(kind, bucket, first, last)
    audit(request, "LIST", "recall_list", count=len(context["rows"]))
    return render(request, "recalls.html", context)
