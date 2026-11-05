"""공통 Recall은 원본 계획을 읽고 미래 종류·임상 주기를 임의로 추가하지 않는다."""

from dataclasses import replace
from datetime import date, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from app.kernel.recall import RecallItem, RecallRegistry
from app.kernel.web import UserError
from app.main import create_app
from app.modules.endoscopy_pathology.manual_dashboard import ManualDashboardService
from ledger_helpers import FixedClock


def test_registry_filters_dates_and_reflects_source_completion():
    registry = RecallRegistry(FixedClock())
    today = date(2026, 11, 5)
    items = [RecallItem("ENDOSCOPY", uuid4(), day, None, None, "/dashboard") for day in
             (today - timedelta(days=1), today, today + timedelta(days=1))]
    registry.register("ENDOSCOPY", lambda: items)
    assert registry.snapshot()["counts"] == {"due": 2, "upcoming": 1, "done": 0, "open": 3, "all": 3}
    assert len(registry.snapshot(start=today)["rows"]) == 1
    items[0] = replace(items[0], done_on=today, done_by="테스트직원")
    snap = registry.snapshot(bucket="done")
    assert snap["rows"] == [items[0]] and snap["counts"]["open"] == 2
    assert len(registry.snapshot(kind="ENDOSCOPY", bucket="all", start=today, end=today)["rows"]) == 1


def test_unapproved_kind_duplicate_and_invalid_filters_are_rejected():
    registry = RecallRegistry(FixedClock())
    with pytest.raises(ValueError):
        registry.register("BMD", lambda: [])
    registry.register("ENDOSCOPY", lambda: [])
    with pytest.raises(ValueError):
        registry.register("ENDOSCOPY", lambda: [])
    for kwargs in ({"kind": "BMD"}, {"bucket": "NOPE"}, {"start": date(2026, 11, 6), "end": date(2026, 11, 5)}):
        with pytest.raises(UserError):
            registry.snapshot(**kwargs)


def test_original_links_are_authorized_and_schedule_is_not_copied():
    service = ManualDashboardService(clock=FixedClock())
    app = create_app(service)
    with TestClient(app) as client:
        response = client.get("/recalls?bucket=all")
        assert response.status_code == 200
        assert "테스트환자" not in response.text
        snapshot = app.state.recalls.snapshot(bucket="all")
        assert snapshot["rows"]
        for row in snapshot["rows"]:
            assert client.get(row.source_url).status_code == 200
        assert 'href="/recalls"' in client.get("/dashboard?stage=FOLLOWUP").text
        assert client.get("/recalls?start=&end=").status_code == 200
        assert client.get("/recalls?start=bad").status_code == 422
        assert client.get("/recalls?kind=BMD").status_code == 422
        before = snapshot["rows"]
        for _ in range(3):
            client.get("/recalls")
        assert app.state.recalls.snapshot(bucket="all")["rows"] == before
