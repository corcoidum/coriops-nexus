"""장부 한 줄(ledger_entries)을 환자·검사·검체·결과·원장 지시·재검 테이블로 나눈다(Stage A-2, A14).

- 이전 전에 같은 차트번호의 이름 충돌 등을 점검하고, 있으면 건수만 알리고 멈춘다(차트번호·이름은 출력하지 않음).
- 옮긴 뒤 새 테이블로 다시 조립한 값이 기존 행과 한 칸도 다르지 않은지 확인하고, 다르면 전체를 되돌린다.
- 기존 테이블은 ledger_entries_legacy로 이름만 바꿔 한 단계 동안 남긴다(새 기록은 반영되지 않는 이전 시점 사본).
- downgrade는 새 테이블에서 ledger_entries를 다시 만든다. 새로 생긴 기록자(decided_by·done_by)는 버려진다.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0003_split_ledger_entries"
down_revision = "0002_auth_access_logs"
branch_labels = None
depends_on = None

COLUMNS = ("id, version, kind, source, chart_no, patient_name, sex, age, exam_date, procedure_type, specimen_count, "
           "site, report_ref, registered_by, handed_by, received_by, handoff_id, entrusted_on, reported_on, findings, "
           "sydney, result_code, review_codes, decided_at, followup_due, no_followup_reason, followup_done_on, "
           "import_batch_id, created_at, updated_at")

# 새 테이블을 기존 한 줄 모양으로 다시 조립한다. 검증과 downgrade에 함께 쓴다.
REASSEMBLED = """
    SELECT e.id, e.version, e.kind, e.source, p.chart_no, p.name AS patient_name, e.sex, e.age, e.exam_date,
           e.procedure_type, s.specimen_count, s.site, e.report_ref, s.registered_by, s.handed_by, s.received_by,
           s.handoff_id, s.entrusted_on, r.reported_on, COALESCE(r.findings, '[]'::jsonb) AS findings,
           COALESCE(r.sydney, '{}'::jsonb) AS sydney, COALESCE(r.result_code, '') AS result_code,
           COALESCE(r.review_codes, '[]'::jsonb) AS review_codes, d.decided_at, f.due_on AS followup_due,
           COALESCE(d.no_followup_reason, '') AS no_followup_reason, f.done_on AS followup_done_on,
           e.import_batch_id, e.created_at, e.updated_at
    FROM exams e
    JOIN patients p ON p.id = e.patient_id
    JOIN specimens s ON s.exam_id = e.id
    LEFT JOIN exam_results r ON r.exam_id = e.id
    LEFT JOIN doctor_reviews d ON d.exam_id = e.id
    LEFT JOIN followups f ON f.review_id = d.id
"""

# (설명, 문제 행 수를 세는 SQL). 하나라도 0이 아니면 이전하지 않는다.
PRECHECKS = (
    ("같은 차트번호에 이름이 둘 이상인 차트번호",
     "SELECT count(*) FROM (SELECT chart_no FROM ledger_entries GROUP BY chart_no "
     "HAVING count(DISTINCT patient_name) > 1) conflict"),
    ("원장 지시 없이 재검 날짜·사유·완료일이 있는 행",
     "SELECT count(*) FROM ledger_entries WHERE decided_at IS NULL AND (followup_due IS NOT NULL "
     "OR no_followup_reason <> '' OR followup_done_on IS NOT NULL)"),
    ("재검 날짜 없이 재검 완료일이 있는 행",
     "SELECT count(*) FROM ledger_entries WHERE followup_due IS NULL AND followup_done_on IS NOT NULL"),
    ("성별이 M·F·빈칸이 아닌 행",
     "SELECT count(*) FROM ledger_entries WHERE sex IS NOT NULL AND sex NOT IN ('M', 'F')"),
)


def _timestamps():
    return [sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False)]


def _uuid(name: str, target: str | None = None, **kwargs) -> sa.Column:
    args = [sa.ForeignKey(target)] if target else []
    return sa.Column(name, pg.UUID(as_uuid=True), *args, **kwargs)


def _create_tables() -> None:
    op.create_table(
        "patients",
        _uuid("id", primary_key=True),
        sa.Column("chart_no", sa.Text, nullable=False, unique=True),
        sa.Column("name", sa.Text, nullable=False),
        *_timestamps(),
    )
    op.create_table(
        "exams",
        _uuid("id", primary_key=True),
        _uuid("patient_id", "patients.id", nullable=False),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("exam_date", sa.Date, nullable=False),
        sa.Column("procedure_type", sa.Text),
        sa.Column("age", sa.Integer),
        sa.Column("sex", sa.Text),
        sa.Column("report_ref", sa.Text),
        sa.Column("source", sa.Text, nullable=False),
        _uuid("import_batch_id", "ledger_import_batches.id"),
        sa.Column("version", sa.Integer, nullable=False),
        *_timestamps(),
        sa.CheckConstraint("kind IN ('BIOPSY', 'CLO', 'STOOL')", name="ck_exams_kind"),
        sa.CheckConstraint("source IN ('MANUAL', 'IMPORT', 'SEED')", name="ck_exams_source"),
        sa.CheckConstraint("procedure_type IS NULL OR procedure_type IN ('stomach', 'colon')",
                           name="ck_exams_procedure"),
        sa.CheckConstraint("sex IS NULL OR sex IN ('M', 'F')", name="ck_exams_sex"),
        sa.UniqueConstraint("kind", "report_ref", name="uq_exams_report_ref"),
    )
    op.create_index("ix_exams_patient_id", "exams", ["patient_id"])
    op.create_table(
        "specimens",
        _uuid("id", primary_key=True),
        _uuid("exam_id", "exams.id", nullable=False, unique=True),
        sa.Column("specimen_count", sa.Integer),
        sa.Column("site", sa.Text, nullable=False),
        _uuid("handoff_id", "ledger_handoffs.id"),
        sa.Column("registered_by", sa.Text, nullable=False),
        sa.Column("handed_by", sa.Text, nullable=False),
        sa.Column("received_by", sa.Text, nullable=False),
        sa.Column("entrusted_on", sa.Date),
        *_timestamps(),
        sa.CheckConstraint("specimen_count IS NULL OR specimen_count BETWEEN 1 AND 99", name="ck_specimens_count"),
    )
    op.create_index("ix_specimens_handoff_id", "specimens", ["handoff_id"])
    op.create_table(
        "exam_results",
        _uuid("id", primary_key=True),
        _uuid("exam_id", "exams.id", nullable=False, unique=True),
        sa.Column("reported_on", sa.Date),
        sa.Column("result_code", sa.Text, nullable=False),
        sa.Column("findings", pg.JSONB, nullable=False),
        sa.Column("sydney", pg.JSONB, nullable=False),
        sa.Column("review_codes", pg.JSONB, nullable=False),
        *_timestamps(),
    )
    op.create_table(
        "doctor_reviews",
        _uuid("id", primary_key=True),
        _uuid("exam_id", "exams.id", nullable=False, unique=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_by", sa.Text),
        sa.Column("no_followup_reason", sa.Text, nullable=False),
        *_timestamps(),
    )
    op.create_table(
        "followups",
        _uuid("id", primary_key=True),
        _uuid("review_id", "doctor_reviews.id", nullable=False, unique=True),
        sa.Column("due_on", sa.Date, nullable=False),
        sa.Column("done_on", sa.Date),
        sa.Column("done_by", sa.Text),
        *_timestamps(),
    )


def _count(sql: str) -> int:
    return op.get_bind().execute(sa.text(sql)).scalar_one()


def upgrade() -> None:
    problems = [f"{label} {count}건" for label, sql in PRECHECKS if (count := _count(sql))]
    if problems:
        raise RuntimeError("장부 이전을 멈췄습니다: " + ", ".join(problems)
                           + ". docs/ledger-app.md의 '테이블 분리 이전' 절차로 정리한 뒤 다시 실행하세요.")
    _create_tables()
    op.execute("""
        INSERT INTO patients (id, chart_no, name, created_at, updated_at)
        SELECT gen_random_uuid(), chart_no, min(patient_name), min(created_at), max(updated_at)
        FROM ledger_entries GROUP BY chart_no
    """)
    op.execute("""
        INSERT INTO exams (id, patient_id, kind, exam_date, procedure_type, age, sex, report_ref, source,
                           import_batch_id, version, created_at, updated_at)
        SELECT e.id, p.id, e.kind, e.exam_date, e.procedure_type, e.age, e.sex, e.report_ref, e.source,
               e.import_batch_id, e.version, e.created_at, e.updated_at
        FROM ledger_entries e JOIN patients p ON p.chart_no = e.chart_no
    """)
    op.execute("""
        INSERT INTO specimens (id, exam_id, specimen_count, site, handoff_id, registered_by, handed_by, received_by,
                               entrusted_on, created_at, updated_at)
        SELECT gen_random_uuid(), id, specimen_count, site, handoff_id, registered_by, handed_by, received_by,
               entrusted_on, created_at, updated_at
        FROM ledger_entries
    """)
    op.execute("""
        INSERT INTO exam_results (id, exam_id, reported_on, result_code, findings, sydney, review_codes,
                                  created_at, updated_at)
        SELECT gen_random_uuid(), id, reported_on, result_code, findings, sydney, review_codes, updated_at, updated_at
        FROM ledger_entries
        WHERE reported_on IS NOT NULL OR result_code <> '' OR findings <> '[]'::jsonb OR sydney <> '{}'::jsonb
           OR review_codes <> '[]'::jsonb
    """)
    op.execute("""
        INSERT INTO doctor_reviews (id, exam_id, decided_at, decided_by, no_followup_reason, created_at, updated_at)
        SELECT gen_random_uuid(), id, decided_at, NULL, no_followup_reason, decided_at, updated_at
        FROM ledger_entries WHERE decided_at IS NOT NULL
    """)
    op.execute("""
        INSERT INTO followups (id, review_id, due_on, done_on, done_by, created_at, updated_at)
        SELECT gen_random_uuid(), d.id, e.followup_due, e.followup_done_on, NULL, d.created_at, e.updated_at
        FROM ledger_entries e JOIN doctor_reviews d ON d.exam_id = e.id
        WHERE e.followup_due IS NOT NULL
    """)
    # 기존 행과 다시 조립한 행이 양쪽으로 한 줄도 남지 않아야 한다(건수·결과·재검 일정 모두 포함).
    missing = _count(f"SELECT count(*) FROM (SELECT {COLUMNS} FROM ledger_entries "
                     f"EXCEPT ALL SELECT {COLUMNS} FROM ({REASSEMBLED}) x) diff")
    extra = _count(f"SELECT count(*) FROM (SELECT {COLUMNS} FROM ({REASSEMBLED}) x "
                   f"EXCEPT ALL SELECT {COLUMNS} FROM ledger_entries) diff")
    if missing or extra:
        raise RuntimeError(f"장부 이전 검증 실패(누락 {missing}건, 추가 {extra}건). 전체를 되돌립니다.")
    op.rename_table("ledger_entries", "ledger_entries_legacy")


def downgrade() -> None:
    op.rename_table("ledger_entries_legacy", "ledger_entries")
    op.execute("DELETE FROM ledger_entries")
    op.execute(f"INSERT INTO ledger_entries ({COLUMNS}) SELECT {COLUMNS} FROM ({REASSEMBLED}) x")
    for table in ("followups", "doctor_reviews", "exam_results", "specimens"):
        op.drop_table(table)
    op.drop_index("ix_exams_patient_id", table_name="exams")
    op.drop_table("exams")
    op.drop_table("patients")
