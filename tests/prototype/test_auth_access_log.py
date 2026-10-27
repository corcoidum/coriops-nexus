"""로그인·세션·권한·접속기록. 실제 PostgreSQL 16과 Alembic 스키마로 시험한다."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.exc import DBAPIError

from app.kernel.access_log import AccessLogger
from app.kernel.auth import Actor, AuthError, AuthService
from app.kernel.security_db import access_logs, metadata as kernel_metadata, permission_history, staff
from app.main import create_app
from app.manage import main as manage_main
from app.modules.endoscopy_pathology.ledger_db import PostgresStore, database_url
from app.modules.endoscopy_pathology.manual_dashboard import ManualDashboardService
from ledger_helpers import FixedClock

ROOT = Path(__file__).resolve().parents[2]
PASSWORD = "합성-비밀번호-0001"
ALL_TABLES = ("access_log_reviews", "access_logs", "auth_sessions", "permission_history", "staff_roles", "staff",
              "followups", "doctor_reviews", "exam_results", "specimens", "exams", "patients", "ledger_exports",
              "ledger_import_batches", "ledger_handoffs")


def alembic_config() -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    return config


@pytest.fixture(scope="module")
def engine():
    engine = create_engine(database_url())
    command.upgrade(alembic_config(), "head")
    yield engine
    engine.dispose()


@pytest.fixture
def clean(engine):
    # 추가 전용 트리거를 잠시 끄고(복제 모드) 시험 사이에만 비운다. 앱 계정에는 이 권한을 주지 않는다.
    with engine.begin() as connection:
        connection.execute(text("SET LOCAL session_replication_role = replica"))
        connection.execute(text("TRUNCATE " + ", ".join(ALL_TABLES) + " CASCADE"))
    return engine


@pytest.fixture
def clock():
    return FixedClock()


@pytest.fixture
def parts(clean, clock, tmp_path):
    auth = AuthService(clean, clock)
    logger = AccessLogger(clean, clock)
    service = ManualDashboardService(clock=clock, store=PostgresStore(clean), export_dir=tmp_path)
    app = create_app(service, auth=auth, access_log=logger)
    return app, auth, logger, service


def make_staff(auth, username, roles, must_change=False):
    return auth.create_staff(username, f"테스트 {username}", roles, PASSWORD, changed_by=None, reason="합성 시험",
                             must_change_password=must_change)


OFFICE_PC = ("192.168.0.20", 50000)  # config/security.yaml의 [가정] 업무 PC 대역 안


def client_for(app, client=OFFICE_PC) -> TestClient:
    return TestClient(app, base_url="https://testserver", client=client)


def login(client, username, password=PASSWORD):
    return client.post("/login", data={"username": username, "password": password}, follow_redirects=False)


def csrf(client) -> str:
    page = client.get("/account/password").text
    return page.split('name="csrf_token" value="')[1].split('"')[0]


def logs(engine):
    with engine.connect() as connection:
        return connection.execute(select(access_logs).order_by(access_logs.c.sequence_no)).all()


# ---------- 스키마·추가 전용

def test_kernel_schema_matches_code_and_is_append_only(engine, clean):
    inspector = inspect(engine)
    for table in kernel_metadata.sorted_tables:
        columns = {c["name"]: c for c in inspector.get_columns(table.name)}
        assert set(columns) == set(table.columns.keys()), table.name
        assert str(columns["id"]["type"]) == "UUID"
    AccessLogger(engine).record(actor_id=None, actor_label="t", client_ip="local", action="LOGIN", target_type="t")
    AuthService(engine).create_staff("history1", "합성", ["NURSE"], PASSWORD, changed_by=None, reason="합성")
    for sql in ("UPDATE access_logs SET outcome = 'X'", "DELETE FROM access_logs", "TRUNCATE access_logs",
                "DELETE FROM permission_history"):
        with pytest.raises(DBAPIError, match="APPEND_ONLY_TABLE"):
            with engine.begin() as connection:
                connection.execute(text(sql))
    assert len(logs(engine)) == 1


# ---------- 계정·비밀번호

def test_passwords_are_stored_as_argon2id_only(parts, clean):
    _, auth, _, _ = parts
    make_staff(auth, "nurse1", ["NURSE"])
    with clean.connect() as connection:
        stored = connection.execute(select(staff.c.password_hash)).scalar_one()
    assert stored.startswith("$argon2id$") and PASSWORD not in stored


@pytest.mark.parametrize(("username", "password", "code"), [
    ("nurse1", "short", "WEAK_PASSWORD"),
    ("nurse1", "xxnurse1xxyy", "WEAK_PASSWORD"),
    ("NO SPACES", PASSWORD, "INVALID_USERNAME"),
])
def test_weak_passwords_and_bad_usernames_are_rejected(parts, username, password, code):
    _, auth, _, _ = parts
    with pytest.raises(AuthError) as error:
        auth.create_staff(username, "테스트", ["NURSE"], password, changed_by=None, reason="합성")
    assert error.value.code == code


# ---------- 로그인·세션

def test_login_sets_strict_cookie_and_forces_first_password_change(parts):
    app, auth, _, _ = parts
    make_staff(auth, "admin1", ["ADMIN"], must_change=True)
    with client_for(app) as client:
        response = login(client, "admin1")
        assert response.status_code == 303 and response.headers["location"] == "/account/password"
        cookie = response.headers["set-cookie"].lower()
        assert "httponly" in cookie and "secure" in cookie and "samesite=strict" in cookie
        assert client.get("/dashboard", follow_redirects=False).headers["location"] == "/account/password"
        token = csrf(client)
        changed = client.post("/account/password", data={"csrf_token": token, "current": PASSWORD,
                                                         "new": "새-합성-비밀번호-02", "confirm": "새-합성-비밀번호-02"},
                              follow_redirects=False)
        assert changed.status_code == 303
        assert client.get("/dashboard").status_code == 200


def test_anonymous_requests_are_sent_to_login(parts):
    app, *_ = parts
    with client_for(app) as client:
        assert client.get("/dashboard", follow_redirects=False).headers["location"] == "/login"
        assert client.post("/ledger/handoff", data={}).status_code == 401
        assert client.get("/login").status_code == 200


def test_five_failures_lock_for_thirty_minutes_and_log_without_typed_names(parts, clock, clean):
    app, auth, _, _ = parts
    make_staff(auth, "nurse1", ["NURSE"])
    with client_for(app) as client:
        for _ in range(5):
            assert login(client, "nurse1", "틀린-비밀번호-0000").status_code == 401
        assert login(client, "nurse1").status_code == 423  # 맞는 비밀번호도 잠김
        assert login(client, "typed-unknown-name", "아무거나-0000000").status_code == 401
        clock.moment += timedelta(minutes=31)
        assert login(client, "nurse1").status_code == 303
    rows = logs(clean)
    fails = [r for r in rows if r.action == "LOGIN_FAIL"]
    assert [r.outcome for r in fails] == ["INVALID"] * 4 + ["LOCKED_NOW", "LOCKED", "INVALID"]
    assert fails[-1].actor_label == "unknown" and fails[0].actor_id is not None
    assert all("typed-unknown-name" not in str(tuple(r)) for r in rows)
    assert rows[-1].action == "LOGIN"


def test_idle_and_absolute_timeouts_end_the_session(parts, clock):
    app, auth, _, _ = parts
    make_staff(auth, "nurse1", ["NURSE"])
    with client_for(app) as client:
        login(client, "nurse1")
        clock.moment += timedelta(minutes=14)
        assert client.get("/dashboard").status_code == 200
        clock.moment += timedelta(minutes=16)
        assert client.get("/dashboard", follow_redirects=False).headers["location"] == "/login?notice=expired"
        login(client, "nurse1")
        for _ in range(52):  # 14분마다 활동해도 12시간(720분)이 지나면 끝난다
            clock.moment += timedelta(minutes=14)
            client.get("/dashboard")
        assert client.get("/dashboard", follow_redirects=False).status_code == 303


def test_logout_revokes_the_server_session(parts):
    app, auth, _, _ = parts
    make_staff(auth, "nurse1", ["NURSE"])
    with client_for(app) as client:
        login(client, "nurse1")
        cookie = client.cookies.get("coriops_session")
        assert client.post("/logout", data={"csrf_token": csrf(client)}, follow_redirects=False).status_code == 303
    with client_for(app) as other:
        other.cookies.set("coriops_session", cookie)
        assert other.get("/dashboard", follow_redirects=False).headers["location"].startswith("/login")


def test_cross_site_posts_and_missing_csrf_are_rejected(parts):
    app, auth, _, _ = parts
    make_staff(auth, "admin1", ["ADMIN"])
    with client_for(app) as client:
        login(client, "admin1")
        token = csrf(client)
        foreign = client.post("/ledger/register", data={"csrf_token": token}, headers={"Origin": "https://evil.example"})
        missing = client.post("/ledger/register", data={"kind": "CLO"})
    assert foreign.status_code == 403 and missing.status_code == 403


# ---------- 권한

@pytest.mark.parametrize(("roles", "path", "allowed"), [
    (["NURSE"], "/dashboard", True),
    (["NURSE"], "/admin/staff", False),
    (["NURSE"], "/privacy/access-logs", False),
    (["ADMIN"], "/privacy/access-logs", False),
    (["PRIVACY_OFFICER"], "/dashboard", False),
    (["PRIVACY_OFFICER"], "/privacy/access-logs", True),
    (["PRIVACY_OFFICER"], "/admin/staff", True),
])
def test_pages_follow_the_role_matrix(parts, clean, roles, path, allowed):
    app, auth, _, _ = parts
    make_staff(auth, "person1", roles)
    with client_for(app) as client:
        login(client, "person1")
        status = client.get(path).status_code
    assert (status == 200) is allowed
    if not allowed:
        assert status == 403 and logs(clean)[-1].action == "DENIED"


def test_nurse_can_register_but_not_record_results_or_decisions(parts, clean):
    app, auth, _, service = parts
    make_staff(auth, "nurse1", ["NURSE"])
    with client_for(app) as client:
        login(client, "nurse1")
        token = csrf(client)
        created = client.post("/ledger/register", data={
            "csrf_token": token, "kind": "CLO", "chart_no": "N-0001", "patient_name": "합성환자",
            "exam_date": "2026-11-05"}, follow_redirects=False)
        assert created.status_code == 303
        entry_id = service._store.entries()[0].id
        denied = client.post(f"/ledger/cases/{entry_id}/receive", data={"csrf_token": token, "result_notation": "+"})
    assert denied.status_code == 403
    assert service._store.entries()[0].reported_on is None


# ---------- 접속기록 내용

def test_views_changes_and_exports_are_logged_per_chart_and_chain_verifies(parts, clean):
    app, auth, logger, service = parts
    make_staff(auth, "admin1", ["ADMIN"])
    service.register("BIOPSY", "C-0001", "합성일", date(2026, 11, 5), procedure_type="colon", specimen_count="1")
    service.register("BIOPSY", "C-0002", "합성이", date(2026, 11, 5), procedure_type="stomach", specimen_count="1")
    with client_for(app) as client:
        login(client, "admin1")
        client.get("/dashboard")
        token = csrf(client)
        client.post("/ledger/export", data={"csrf_token": token})
    rows = logs(clean)
    by_action = {}
    for row in rows:
        by_action.setdefault(row.action, []).append(row)
    assert {r.subject_ref for r in by_action["LIST"]} == {"C-0001", "C-0002"}
    assert len(by_action["VIEW"]) == 1 and by_action["VIEW"][0].subject_ref in {"C-0001", "C-0002"}
    assert by_action["EXPORT"][0].detail_count == 2
    assert all(r.actor_label == "admin1" and r.client_ip for r in rows if r.action != "LOGIN_FAIL")
    assert [r.sequence_no for r in rows] == list(range(1, len(rows) + 1))
    assert logger.verify()["ok"] is True


def test_tampering_is_detected_at_the_changed_row(parts, clean):
    _, _, logger, _ = parts
    for number in range(5):
        logger.record(actor_id=None, actor_label="t", client_ip="local", action="VIEW", target_type="t",
                      subjects=[f"C-{number}"])
    with clean.begin() as connection:
        connection.execute(text("SET LOCAL session_replication_role = replica"))
        connection.execute(text("UPDATE access_logs SET subject_ref = 'C-9' WHERE sequence_no = 3"))
    assert logger.verify() == {**logger.verify(), "ok": False, "broken_at": 3}
    with clean.begin() as connection:
        connection.execute(text("SET LOCAL session_replication_role = replica"))
        connection.execute(text("DELETE FROM access_logs WHERE sequence_no = 3"))
    assert logger.verify()["broken_at"] == 4


def test_bulk_view_warning_and_review_record(parts, clock, clean):
    _, auth, logger, _ = parts
    officer = make_staff(auth, "officer1", ["PRIVACY_OFFICER"])
    logger.record(actor_id=None, actor_label="busy", client_ip="local", action="VIEW", target_type="t",
                  subjects=[f"C-{n}" for n in range(51)])
    logger.record(actor_id=None, actor_label="calm", client_ip="local", action="VIEW", target_type="t",
                  subjects=[f"C-{n}" for n in range(50)])
    start, end = clock.moment - timedelta(days=1), clock.moment + timedelta(days=1)
    alerts = logger.bulk_alerts(start, end)
    assert [(a["actor_label"], a["distinct"]) for a in alerts] == [("busy", 51)]
    logger.add_review(officer, start, end, "합성 점검")
    review = logger.reviews()[0]
    assert review["last_sequence"] == 101 and review["chain_ok"] is True and review["bulk_alerts"] == 1


def test_access_log_page_is_itself_logged(parts, clean):
    app, auth, _, _ = parts
    make_staff(auth, "officer1", ["PRIVACY_OFFICER"])
    with client_for(app) as client:
        login(client, "officer1")
        page = client.get("/privacy/access-logs?subject=C-0001")
    assert page.status_code == 200 and "위·변조 검사" in page.text
    last = logs(clean)[-1]
    assert (last.action, last.subject_ref) == ("LOG_VIEW", "C-0001")


# ---------- 계정 관리

def test_role_change_revokes_sessions_and_writes_history(parts, clean):
    app, auth, _, _ = parts
    make_staff(auth, "officer1", ["PRIVACY_OFFICER"])
    nurse = make_staff(auth, "nurse1", ["NURSE"])
    with client_for(app) as nurse_client, client_for(app) as officer:
        login(nurse_client, "nurse1")
        assert nurse_client.get("/dashboard").status_code == 200
        login(officer, "officer1")
        changed = officer.post(f"/admin/staff/{nurse}/roles", data={
            "csrf_token": csrf(officer), "roles": ["NURSE", "ADMIN"], "reason": "합성 업무 변경"},
            follow_redirects=False)
        assert changed.status_code == 303
        assert nurse_client.get("/dashboard", follow_redirects=False).status_code == 303  # 즉시 로그아웃
    with clean.connect() as connection:
        history = connection.execute(select(permission_history).where(permission_history.c.staff_id == nurse)
                                     .order_by(permission_history.c.at)).all()
    assert [h.after_roles for h in history] == [["NURSE"], ["ADMIN", "NURSE"]]


def test_last_privacy_officer_and_self_changes_are_protected(parts):
    app, auth, _, _ = parts
    officer = make_staff(auth, "officer1", ["PRIVACY_OFFICER", "DOCTOR"])
    with client_for(app) as client:
        login(client, "officer1")
        token = csrf(client)
        self_cut = client.post(f"/admin/staff/{officer}/roles", data={"csrf_token": token, "roles": ["DOCTOR"],
                                                                     "reason": "합성"})
        self_off = client.post(f"/admin/staff/{officer}/active", data={"csrf_token": token, "active": "0",
                                                                      "reason": "합성"})
    assert self_cut.status_code == 403 and self_off.status_code == 403
    # 책임자가 아닌 주체(예: 오프라인 도구)도 마지막 책임자를 없앨 수 없다.
    outsider = Actor(None, "system", "system", frozenset(), "x")
    with pytest.raises(AuthError) as error:
        auth.set_roles(officer, ["DOCTOR"], by=outsider, reason="합성")
    assert error.value.code == "LAST_OFFICER"
    with pytest.raises(AuthError) as error:
        auth.set_active(officer, False, by=outsider, reason="합성")
    assert error.value.code == "LAST_OFFICER"


def test_deactivated_account_cannot_log_in(parts):
    app, auth, _, _ = parts
    make_staff(auth, "officer1", ["PRIVACY_OFFICER"])
    nurse = make_staff(auth, "nurse1", ["NURSE"])
    actor, _ = auth.login("officer1", PASSWORD)
    auth.set_active(nurse, False, by=actor, reason="합성 퇴사")
    with client_for(app) as client:
        assert login(client, "nurse1").status_code == 403


def test_manage_cli_creates_the_first_officer_with_forced_change(clean):
    answers = iter([PASSWORD, PASSWORD])
    assert manage_main(["create-staff", "--username", "wonjang", "--display-name", "원장",
                        "--roles", "DOCTOR,PRIVACY_OFFICER"], read_password=lambda _: next(answers)) == 0
    auth = AuthService(clean)
    actor, _ = auth.login("wonjang", PASSWORD)
    assert actor.roles == {"DOCTOR", "PRIVACY_OFFICER"} and actor.must_change_password is True
    assert logs(clean)[-1].actor_label == "SYSTEM:manage"
    mismatch = iter([PASSWORD, "다른-비밀번호-0002"])
    assert manage_main(["create-staff", "--username", "nurse9", "--display-name", "간호", "--roles", "NURSE"],
                       read_password=lambda _: next(mismatch)) == 2


def test_memory_demo_keeps_working_without_login():
    app = create_app()
    with TestClient(app) as client:
        assert client.get("/dashboard").status_code == 200
        assert client.get("/admin/staff").status_code == 404
        assert client.get("/login", follow_redirects=False).headers["location"] == "/"


def test_lab_demo_tab_is_not_mounted_in_db_mode(parts):
    # 혈액검체 탭은 저장소가 없는 합성 시연이므로 DB 모드에서는 화면·메뉴가 없어야 한다.
    app, auth, _, _ = parts
    assert app.state.lab_service is None
    make_staff(auth, "admin1", ["ADMIN"])
    with client_for(app) as client:
        login(client, "admin1")
        assert 'href="/lab"' not in client.get("/dashboard").text
        assert client.get("/lab").status_code == 404
        # 첫 화면에는 조직검체 카드만 있고 위급치 알림도 없다.
        home = client.get("/").text
        assert "오늘 할 일" in home and "조직검체 장부 열기" in home
        assert "혈액검체 장부 열기" not in home and "critical-alert" not in home


# ---------- 접속 대역 제한 (고시 제6조①)

def test_outside_network_is_denied_and_logged(parts, clean):
    app, auth, _, _ = parts
    make_staff(auth, "admin1", ["ADMIN"])
    with client_for(app, client=("10.0.0.5", 50000)) as client:
        response = client.get("/login")
        assert response.status_code == 403
        assert "10.0.0.5" in response.text and "원내 업무 PC" in response.text
        # 헤더로 원내 주소를 사칭해도 통과하지 못하고 로그인도 시도할 수 없다.
        spoofed = client.post("/login", data={"username": "admin1", "password": PASSWORD},
                              headers={"X-Forwarded-For": "192.168.0.20"}, follow_redirects=False)
        assert spoofed.status_code == 403 and "coriops_session" not in spoofed.cookies
    denied = [row for row in logs(clean) if row.target_type == "network"]
    assert len(denied) == 2
    assert {(row.action, row.outcome, row.client_ip, row.actor_label) for row in denied} == {
        ("DENIED", "DENIED", "10.0.0.5", "anonymous")}


def test_office_pc_address_is_recorded_in_access_log(parts, clean):
    app, auth, _, _ = parts
    make_staff(auth, "admin1", ["ADMIN"])
    with client_for(app) as client:
        assert login(client, "admin1").status_code == 303
    assert logs(clean)[-1].client_ip == OFFICE_PC[0]
