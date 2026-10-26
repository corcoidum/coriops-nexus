"""규칙·실행 기록·할 일 테이블(Stage B, A17)과 Stage A 이전 시점 사본 삭제.

- rules·rule_runs·tasks를 만든다. 할 일 제목은 고정 문구만 저장한다(이름·차트번호 없음).
- ledger_entries_legacy(0003이 남긴 이전 시점 사본, 이름 포함)를 지운다. 새 기록이 반영되지 않는 사본을
  보관기간 관리 밖에 두지 않기 위해서다.
- downgrade는 사본 테이블을 빈 모양으로 되살린다. 0003 downgrade가 새 테이블에서 장부 한 줄을 다시 만든다.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0004_rules_tasks"
down_revision = "0003_split_ledger_entries"
branch_labels = None
depends_on = None

STATUSES = "'OPEN', 'DONE', 'DISMISSED', 'AUTO_RESOLVED'"
PRIORITIES = "'NORMAL', 'HIGH', 'URGENT'"
ROLES = "'DOCTOR', 'ADMIN', 'NURSE', 'PRIVACY_OFFICER'"


def _timestamps():
    return [sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False)]


def _uuid(name: str, target: str | None = None, **kwargs) -> sa.Column:
    args = [sa.ForeignKey(target)] if target else []
    return sa.Column(name, pg.UUID(as_uuid=True), *args, **kwargs)


def upgrade() -> None:
    op.create_table(
        "rules",
        _uuid("id", primary_key=True),
        sa.Column("rule_id", sa.Text, nullable=False, unique=True),
        sa.Column("params", pg.JSONB, nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False),
        sa.Column("config_hash", sa.Text, nullable=False),
        *_timestamps(),
    )
    op.create_table(
        "rule_runs",
        _uuid("id", primary_key=True),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scope", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("config_hash", sa.Text, nullable=False),
        sa.Column("candidate_count", sa.Integer, nullable=False),
        sa.Column("created_count", sa.Integer, nullable=False),
        sa.Column("resolved_count", sa.Integer, nullable=False),
        sa.Column("error_code", sa.Text),
        *_timestamps(),
        sa.CheckConstraint("scope IN ('ALL', 'SUBJECTS')", name="ck_rule_runs_scope"),
        sa.CheckConstraint("status IN ('SUCCEEDED', 'FAILED')", name="ck_rule_runs_status"),
    )
    op.create_index("ix_rule_runs_scope_evaluated", "rule_runs", ["scope", "evaluated_at"])
    op.create_table(
        "tasks",
        _uuid("id", primary_key=True),
        _uuid("rule_id", "rules.id", nullable=False),
        _uuid("run_id", "rule_runs.id", nullable=False),
        sa.Column("subject_type", sa.Text, nullable=False),
        _uuid("subject_id", nullable=False),
        sa.Column("dedupe_key", sa.Text, nullable=False, unique=True),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("priority", sa.Text, nullable=False),
        sa.Column("assignee_role", sa.Text, nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("resolved_by", sa.Text),
        sa.Column("resolution_note", sa.Text, nullable=False),
        *_timestamps(),
        sa.CheckConstraint(f"status IN ({STATUSES})", name="ck_tasks_status"),
        sa.CheckConstraint(f"priority IN ({PRIORITIES})", name="ck_tasks_priority"),
        sa.CheckConstraint(f"assignee_role IN ({ROLES})", name="ck_tasks_assignee_role"),
        sa.CheckConstraint("(status = 'OPEN') = (resolved_at IS NULL)", name="ck_tasks_resolution"),
    )
    op.create_index("ix_tasks_subject_id", "tasks", ["subject_id"])
    op.create_index("ix_tasks_open_due", "tasks", ["status", "due_at"])
    op.drop_table("ledger_entries_legacy")


def downgrade() -> None:
    # 0003이 남겼던 모양 그대로(제약 이름 포함) 빈 사본을 되살린다.
    op.create_table(
        "ledger_entries_legacy",
        _uuid("id", primary_key=True),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("chart_no", sa.Text, nullable=False),
        sa.Column("patient_name", sa.Text, nullable=False),
        sa.Column("sex", sa.Text),
        sa.Column("age", sa.Integer),
        sa.Column("exam_date", sa.Date, nullable=False),
        sa.Column("procedure_type", sa.Text),
        sa.Column("specimen_count", sa.Integer),
        sa.Column("site", sa.Text, nullable=False),
        sa.Column("report_ref", sa.Text),
        sa.Column("registered_by", sa.Text, nullable=False),
        sa.Column("handed_by", sa.Text, nullable=False),
        sa.Column("received_by", sa.Text, nullable=False),
        _uuid("handoff_id", "ledger_handoffs.id"),
        sa.Column("entrusted_on", sa.Date),
        sa.Column("reported_on", sa.Date),
        sa.Column("findings", pg.JSONB, nullable=False),
        sa.Column("sydney", pg.JSONB, nullable=False),
        sa.Column("result_code", sa.Text, nullable=False),
        sa.Column("review_codes", pg.JSONB, nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("followup_due", sa.Date),
        sa.Column("no_followup_reason", sa.Text, nullable=False),
        sa.Column("followup_done_on", sa.Date),
        _uuid("import_batch_id", "ledger_import_batches.id"),
        *_timestamps(),
        sa.CheckConstraint("kind IN ('BIOPSY', 'CLO', 'STOOL')", name="ck_ledger_entries_kind"),
        sa.CheckConstraint("source IN ('MANUAL', 'IMPORT', 'SEED')", name="ck_ledger_entries_source"),
        sa.CheckConstraint("procedure_type IS NULL OR procedure_type IN ('stomach', 'colon')",
                           name="ck_ledger_entries_procedure"),
        sa.CheckConstraint("specimen_count IS NULL OR specimen_count BETWEEN 1 AND 99",
                           name="ck_ledger_entries_count"),
        sa.CheckConstraint("followup_due IS NULL OR no_followup_reason = ''", name="ck_ledger_entries_decision"),
        sa.UniqueConstraint("kind", "report_ref", name="uq_ledger_entries_report_ref"),
    )
    op.create_index("ix_ledger_entries_natural", "ledger_entries_legacy", ["kind", "chart_no", "exam_date"])
    op.drop_table("tasks")
    op.drop_index("ix_rule_runs_scope_evaluated", table_name="rule_runs")
    op.drop_table("rule_runs")
    op.drop_table("rules")
