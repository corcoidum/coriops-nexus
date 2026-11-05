"""PDF 추출·환자 대조·직원 확정·만료와 중복 방지. 합성 파일만 쓴다."""

from dataclasses import replace
from datetime import date, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from app.kernel.auth import Actor
from app.kernel.web import UserError
from app.main import create_app
from app.modules.endoscopy_pathology.manual_dashboard import ManualDashboardService
from app.modules.screening_lab.dashboard import LabDashboardService
from app.modules.screening_lab.pdf_assist import PdfAssist, extract_pdf, parse_text
from ledger_helpers import FixedClock
from pdf_helpers import TEXT, pdf_bytes


@pytest.fixture
def setup():
    clock = FixedClock()
    lab = LabDashboardService(clock=clock)
    case_id = lab.register(chart_no="T-PDF0001", patient_name="테스트PDF", received_date=date(2026, 11, 5),
        exam_kinds=["일반검진6종", "추가b형간염", "추가c형간염"], registered_by="테스트접수")
    actor = Actor(uuid4(), "testpdf", "테스트PDF직원", frozenset({"ADMIN"}), "test-csrf")
    return clock, lab, PdfAssist(lab), actor, case_id


def test_real_pdf_text_extraction_preserves_values(setup):
    _, _, assist, _, _ = setup
    text = extract_pdf(pdf_bytes(), assist.limits)
    parsed = parse_text(text)
    assert parsed.identity["patient_name"] == "테스트PDF"
    assert parsed.rows == (("AST", "52", "H"),)
    assert parsed.qualitative == {"HBsAg": "Neg", "Anti-HBs": "Pos", "Anti-HCV": "Neg"}
    assert parsed.unflagged_count == 1 and parsed.issues == ()


@pytest.mark.parametrize("data", [b"not-pdf", b"%PDF-broken", pdf_bytes(blank=True), pdf_bytes(encrypted=True)])
def test_unreadable_pdf_rejected_without_reflecting_input(setup, data):
    _, _, assist, _, _ = setup
    with pytest.raises(UserError) as error:
        extract_pdf(data, assist.limits)
    assert error.value.status_code == 422 and "TEST-PDF" not in str(error.value)


@pytest.mark.parametrize("content,message", [
    (TEXT.replace("T-PDF0001", "T-OTHER"), "식별정보"),
    (TEXT.replace("2026-11-05", "2026-11-04"), "접수일"),
    (TEXT + "UNKNOWN 999 H\n", "미등록"),
    (TEXT + "AST 48 H\n", "중복"),
    (TEXT.replace("Anti-HCV Neg\n", ""), "간염"),
    (TEXT.replace("REPORT_DATE: 2026-11-05", ""), "식별정보"),
    (TEXT + "PATIENT_NAME: 테스트다른환자\n", "서로 다른"),
])
def test_mismatches_and_unknown_items_block_commit(setup, content, message):
    _, lab, assist, actor, case_id = setup
    token = assist.create(actor, case_id, pdf_bytes(content))
    assert any(message in issue for issue in assist.get(token, actor).issues)
    with pytest.raises(UserError):
        with assist.confirmed(token, actor, True, True):
            pytest.fail("대조 오류로 저장하면 안 됨")
    assert lab.case(case_id).stage == "RESULT_PENDING"


def test_preview_is_session_bound_expires_and_checks_staff_confirmation(setup):
    clock, lab, assist, actor, case_id = setup
    token = assist.create(actor, case_id, pdf_bytes())
    assert lab.case(case_id).stage == "RESULT_PENDING"
    with pytest.raises(UserError) as error:
        assist.get(token, replace(actor, csrf_token="another-session"))
    assert error.value.status_code == 404
    with pytest.raises(UserError):
        with assist.confirmed(token, actor, False, False):
            pass
    clock.moment += timedelta(minutes=16)
    with pytest.raises(UserError) as error:
        assist.get(token, actor)
    assert error.value.status_code == 410


def test_preview_kept_on_failed_write_and_consumed_only_after_success(setup):
    _, lab, assist, actor, case_id = setup
    token = assist.create(actor, case_id, pdf_bytes())
    with pytest.raises(RuntimeError):
        with assist.confirmed(token, actor, True, False):
            raise RuntimeError("SYNTHETIC_FAILURE")
    assert assist.get(token, actor)
    with assist.confirmed(token, actor, True, False) as preview:
        result = preview.parsed
        lab.enter_result(case_id, report_ref=result.identity["report_ref"], report_date=result.report_date,
            rows=list(result.rows), qualitative=result.qualitative, no_flagged=False, entered_by=actor.label)
    assert lab.case(case_id).stage == "CHECK_PENDING" and not lab.case(case_id).critical
    with pytest.raises(UserError):
        assist.get(token, actor)
    new_token = assist.create(actor, case_id, pdf_bytes())
    assert "이미 결과가 입력된 접수입니다." in assist.get(new_token, actor).issues


def test_normal_requires_explicit_no_hl_confirmation(setup):
    _, _, assist, actor, case_id = setup
    token = assist.create(actor, case_id, pdf_bytes(TEXT.replace("AST 52 U/L H", "AST 20 U/L")))
    with pytest.raises(UserError):
        with assist.confirmed(token, actor, True, False):
            pass
    with assist.confirmed(token, actor, True, True):
        pass


def test_pdf_http_preview_does_not_save_until_confirmation(setup):
    clock, lab, _, _, case_id = setup
    app = create_app(ManualDashboardService(clock=clock), lab_service=lab)
    with TestClient(app) as client:
        assert client.get(f"/lab/pdf/{case_id}").status_code == 200
        response = client.post(f"/lab/pdf/preview/{case_id}", data={"csrf_token": app.state.csrf_token},
            files={"file": ("synthetic.pdf", pdf_bytes(), "application/pdf")}, follow_redirects=False)
        assert response.status_code == 303
        page = client.get(response.headers["location"])
        assert "AST 52 H" in page.text and lab.case(case_id).stage == "RESULT_PENDING"
        token = response.headers["location"].rsplit("/", 1)[1]
        path = f"/lab/pdf/commit/{token}"
        assert client.post(path, data={"csrf_token": app.state.csrf_token}).status_code == 422
        assert client.post(path, data={"csrf_token": app.state.csrf_token, "acknowledged": "1"}).status_code == 200
        assert lab.case(case_id).stage == "CHECK_PENDING"
        assert client.post(path, data={"csrf_token": app.state.csrf_token, "acknowledged": "1"}).status_code == 404


def test_limits_unknown_layout_and_explicit_insurance_mapping(setup, monkeypatch):
    _, _, assist, actor, case_id = setup
    assert parse_text(TEXT.replace("AST 52", "D1860 52")).rows == (("AST", "52", "H"),)
    assert parse_text(TEXT.replace("AST 52 U/L H", "AST 52 U/L 0-40 H")).issues
    with pytest.raises(UserError) as error:
        extract_pdf(b"%PDF-" + b"x" * assist.limits["maximum_upload_bytes"], assist.limits)
    assert error.value.status_code == 413
    assist._extract_slot.acquire()
    try:
        with pytest.raises(UserError) as error:
            assist.create(actor, case_id, pdf_bytes())
        assert error.value.status_code == 429
    finally:
        assist._extract_slot.release()
    import subprocess
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("worker", 1)
    monkeypatch.setattr(subprocess, "run", timeout)
    with pytest.raises(UserError) as error:
        extract_pdf(pdf_bytes(), assist.limits)
    assert error.value.status_code == 422


def test_no_csrf_no_extraction_and_oversized_request_rejected(setup, monkeypatch):
    clock, lab, _, _, case_id = setup
    app = create_app(ManualDashboardService(clock=clock), lab_service=lab)
    def unexpected(*args):
        pytest.fail("권한·CSRF 검사 전에 추출하면 안 됨")
    monkeypatch.setattr(app.state.pdf_assist, "create", unexpected)
    with TestClient(app) as client:
        path = f"/lab/pdf/preview/{case_id}"
        assert client.post(path, files={"file": ("synthetic.pdf", pdf_bytes())}).status_code == 403
        assert client.post(path, content=b"", headers={"content-length": "6000000"}).status_code == 413
