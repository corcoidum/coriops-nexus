"""담당별 할 일의 HTTP 경계. 업무 기록·접속기록을 함께 확정한다."""

from typing import Annotated
from urllib.parse import urlencode
from uuid import UUID

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from app.kernel.web import UserError, audit, check_csrf, render, require
from app.task_dashboard import TaskDashboardService


router = APIRouter()


def service(request: Request) -> TaskDashboardService:
    return request.app.state.task_service


Service = Annotated[TaskDashboardService, Depends(service)]


@router.get("/tasks")
def tasks(request: Request, service: Service, bucket: str = "open", scope: str = "mine", notice: str = ""):
    actor = require(request, "ledger.view")
    context = service.snapshot(actor, bucket, scope)
    context["notice"] = "할 일을 처리했습니다." if notice == "closed" else ""
    audit(request, "LIST", "task_list", count=len(context["rows"]))
    return render(request, "tasks.html", context)


@router.post("/tasks/{task_id}/close")
def close(request: Request, service: Service, task_id: UUID, status: Annotated[str, Form()],
          csrf_token: Annotated[str, Form()] = "", note: Annotated[str, Form()] = "",
          bucket: Annotated[str, Form()] = "open", scope: Annotated[str, Form()] = "mine"):
    actor = require(request, "ledger.view")
    check_csrf(request, csrf_token)
    service.validate(bucket, scope)
    try:
        service.assert_can_close(actor, task_id)
    except UserError as error:
        if error.status_code == 403:
            audit(request, "DENIED", "task_close", outcome="DENIED")
        raise
    with service.transaction():
        service.close(actor, task_id, status, note)
        audit(request, "UPDATE", "task_close", count=1)
    return RedirectResponse("/tasks?" + urlencode({"bucket": bucket, "scope": scope, "notice": "closed"}), 303)
