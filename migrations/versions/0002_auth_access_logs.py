"""개인 계정·역할·세션·권한 이력·접속기록(추가만 가능)"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0002_auth_access_logs"
down_revision = "0001_ledger_tables"
branch_labels = None
depends_on = None


def _timestamps():
    return [sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False)]


def upgrade() -> None:
    op.create_table(
        "staff",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("username", sa.Text, nullable=False, unique=True),
        sa.Column("display_name", sa.Text, nullable=False),
        sa.Column("password_hash", sa.Text, nullable=False),
        sa.Column("active", sa.Boolean, nullable=False),
        sa.Column("must_change_password", sa.Boolean, nullable=False),
        sa.Column("failed_login_count", sa.Integer, nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True)),
        *_timestamps(),
    )
    op.create_table(
        "staff_roles",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("staff_id", pg.UUID(as_uuid=True), sa.ForeignKey("staff.id"), nullable=False),
        sa.Column("role", sa.Text, nullable=False),
        *_timestamps(),
        sa.CheckConstraint("role IN ('DOCTOR', 'ADMIN', 'NURSE', 'PRIVACY_OFFICER')", name="ck_staff_roles_role"),
        sa.UniqueConstraint("staff_id", "role", name="uq_staff_roles"),
    )
    op.create_table(
        "permission_history",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("staff_id", pg.UUID(as_uuid=True), sa.ForeignKey("staff.id"), nullable=False),
        sa.Column("changed_by", pg.UUID(as_uuid=True), sa.ForeignKey("staff.id")),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("before_roles", pg.JSONB, nullable=False),
        sa.Column("after_roles", pg.JSONB, nullable=False),
        sa.Column("before_active", sa.Boolean),
        sa.Column("after_active", sa.Boolean, nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
        *_timestamps(),
    )
    op.create_table(
        "auth_sessions",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("staff_id", pg.UUID(as_uuid=True), sa.ForeignKey("staff.id"), nullable=False),
        sa.Column("token_hash", sa.Text, nullable=False, unique=True),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        *_timestamps(),
    )
    op.create_table(
        "access_logs",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("sequence_no", sa.BigInteger, nullable=False, unique=True),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_id", pg.UUID(as_uuid=True), sa.ForeignKey("staff.id")),
        sa.Column("actor_label", sa.Text, nullable=False),
        sa.Column("client_ip", sa.Text, nullable=False),
        sa.Column("action", sa.Text, nullable=False),
        sa.Column("subject_ref", sa.Text),
        sa.Column("target_type", sa.Text, nullable=False),
        sa.Column("detail_count", sa.Integer),
        sa.Column("outcome", sa.Text, nullable=False),
        sa.Column("prev_hash", sa.Text, nullable=False),
        sa.Column("hash", sa.Text, nullable=False),
        *_timestamps(),
    )
    op.create_index("ix_access_logs_at", "access_logs", ["at"])
    op.create_index("ix_access_logs_subject", "access_logs", ["subject_ref"])
    op.create_table(
        "access_log_reviews",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("reviewer_id", pg.UUID(as_uuid=True), sa.ForeignKey("staff.id"), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_sequence", sa.BigInteger, nullable=False),
        sa.Column("last_hash", sa.Text, nullable=False),
        sa.Column("chain_ok", sa.Boolean, nullable=False),
        sa.Column("bulk_alerts", sa.Integer, nullable=False),
        sa.Column("note", sa.Text, nullable=False),
        *_timestamps(),
    )
    # 접속기록·점검·권한 이력은 추가만 한다. 앱 실수나 SQL로 고치거나 지우지 못하게 DB가 거절한다.
    op.execute("""
        CREATE FUNCTION coriops_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'APPEND_ONLY_TABLE: %', TG_TABLE_NAME USING ERRCODE = 'insufficient_privilege';
        END;
        $$
    """)
    for table in ("access_logs", "access_log_reviews", "permission_history"):
        op.execute(f"CREATE TRIGGER {table}_no_update BEFORE UPDATE OR DELETE ON {table} "
                   f"FOR EACH ROW EXECUTE FUNCTION coriops_append_only()")
        op.execute(f"CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON {table} "
                   f"FOR EACH STATEMENT EXECUTE FUNCTION coriops_append_only()")


def downgrade() -> None:
    for table in ("access_logs", "access_log_reviews", "permission_history"):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_no_truncate ON {table}")
        op.execute(f"DROP TRIGGER IF EXISTS {table}_no_update ON {table}")
    op.execute("DROP FUNCTION IF EXISTS coriops_append_only()")
    op.drop_table("access_log_reviews")
    op.drop_index("ix_access_logs_subject", table_name="access_logs")
    op.drop_index("ix_access_logs_at", table_name="access_logs")
    op.drop_table("access_logs")
    op.drop_table("auth_sessions")
    op.drop_table("permission_history")
    op.drop_table("staff_roles")
    op.drop_table("staff")
