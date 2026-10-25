"""'오늘 할 일' 첫 화면. 조립 지점(app/main.py)에서만 붙이며 장부별 건수만 모아 보여준다.

환자 이름·차트번호를 보여주지 않으므로 접속기록 대상이 아니다. 각 장부 화면으로 가는 입구 역할만 한다.
"""

from fastapi import APIRouter, Request

from app.kernel.web import current_actor, render


router = APIRouter()


@router.get("/")
def today(request: Request):
    actor = current_actor(request)
    context: dict = {"tissue": None, "blood": None}
    if actor.can("ledger.view"):
        snap = request.app.state.dashboard_service.snapshot()
        context.update(tissue=snap, today=snap["today"])
        lab = request.app.state.lab_service
        if lab is not None:
            context["blood"] = lab.snapshot()
    return render(request, "home.html", context)
