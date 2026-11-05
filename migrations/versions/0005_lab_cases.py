"""혈액 장부: 공통 환자와 연결한 접수·결과·직원 처리 사실."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg


revision = "0005_lab_cases"
down_revision = "0004_rules_tasks"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "lab_cases", sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("patient_id", pg.UUID(as_uuid=True), sa.ForeignKey("patients.id"), nullable=False),
        sa.Column("received_date", sa.Date(), nullable=False), sa.Column("report_ref", sa.Text(), nullable=False),
        sa.Column("sex", sa.Text()), sa.Column("age", sa.Text()), sa.Column("exam_kinds", pg.JSONB(), nullable=False),
        sa.Column("entrusted_date", sa.Date()), sa.Column("report_date", sa.Date()),
        sa.Column("items", pg.JSONB(), nullable=False), sa.Column("result_received", sa.Boolean(), nullable=False),
        sa.Column("followup_note", sa.Text()),
        *[sa.Column(name, sa.DateTime(timezone=True)) for name in
          ("critical_marked_at", "critical_reported_at", "result_entered_at", "checked_at")],
        *[sa.Column(name, sa.Text(), nullable=False) for name in
          ("critical_marked_by", "critical_reported_by", "result_entered_by", "checked_by", "registered_by")],
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
    )
    op.create_index("uq_lab_report_ref", "lab_cases", ["report_ref"], unique=True, postgresql_where=sa.text("report_ref <> ''"))
    op.create_index("ix_lab_received_date", "lab_cases", ["received_date"])


def downgrade():
    op.drop_table("lab_cases")
