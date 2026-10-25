"""장부·인계·가져오기·출력 테이블 (합성 검증 후 원장 승인 시 실데이터)"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0001_ledger_tables"
down_revision = None
branch_labels = None
depends_on = None


def _timestamps():
    return [sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False)]


def upgrade() -> None:
    op.create_table(
        "ledger_handoffs",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("handed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("registered_by", sa.Text, nullable=False),
        sa.Column("handed_by", sa.Text, nullable=False),
        sa.Column("receiver_name", sa.Text, nullable=False),
        sa.Column("specimen_count", sa.Integer, nullable=False),
        sa.Column("case_count", sa.Integer, nullable=False),
        *_timestamps(),
    )
    op.create_table(
        "ledger_import_batches",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("digest", sa.Text, nullable=False, unique=True),
        sa.Column("accepted", sa.Integer, nullable=False),
        sa.Column("skipped", sa.Integer, nullable=False),
        sa.Column("sheet_counts", pg.JSONB, nullable=False),
        *_timestamps(),
    )
    op.create_table(
        "ledger_exports",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("exported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("file_name", sa.Text, nullable=False),
        sa.Column("row_count", sa.Integer, nullable=False),
        *_timestamps(),
    )
    op.create_table(
        "ledger_entries",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
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
        sa.Column("handoff_id", pg.UUID(as_uuid=True), sa.ForeignKey("ledger_handoffs.id")),
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
        sa.Column("import_batch_id", pg.UUID(as_uuid=True), sa.ForeignKey("ledger_import_batches.id")),
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
    # 검색·대조에 쓰는 자연키. 같은 날 같은 검사가 두 번일 수 있어 UNIQUE로 두지 않는다.
    op.create_index("ix_ledger_entries_natural", "ledger_entries", ["kind", "chart_no", "exam_date"])


def downgrade() -> None:
    op.drop_index("ix_ledger_entries_natural", table_name="ledger_entries")
    op.drop_table("ledger_entries")
    op.drop_table("ledger_exports")
    op.drop_table("ledger_import_batches")
    op.drop_table("ledger_handoffs")
