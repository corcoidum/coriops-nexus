"""계정·세션·권한 이력·접속기록 테이블. 커널 소유이며 업무 모듈을 알지 못한다."""

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Column, DateTime, ForeignKey, Integer, MetaData, Table, Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID


ROLES = ("DOCTOR", "ADMIN", "NURSE", "PRIVACY_OFFICER")
metadata = MetaData()


def _timestamps() -> list[Column]:
    return [Column("created_at", DateTime(timezone=True), nullable=False),
            Column("updated_at", DateTime(timezone=True), nullable=False)]


staff = Table(
    "staff", metadata,
    Column("id", PgUUID(as_uuid=True), primary_key=True),
    Column("username", Text, nullable=False, unique=True),
    Column("display_name", Text, nullable=False),
    Column("password_hash", Text, nullable=False),
    Column("active", Boolean, nullable=False),
    Column("must_change_password", Boolean, nullable=False),
    Column("failed_login_count", Integer, nullable=False),
    Column("locked_until", DateTime(timezone=True)),
    *_timestamps(),
)

staff_roles = Table(
    "staff_roles", metadata,
    Column("id", PgUUID(as_uuid=True), primary_key=True),
    Column("staff_id", PgUUID(as_uuid=True), ForeignKey("staff.id"), nullable=False),
    Column("role", Text, nullable=False),
    *_timestamps(),
    CheckConstraint("role IN ('DOCTOR', 'ADMIN', 'NURSE', 'PRIVACY_OFFICER')", name="ck_staff_roles_role"),
    UniqueConstraint("staff_id", "role", name="uq_staff_roles"),
)

permission_history = Table(
    "permission_history", metadata,
    Column("id", PgUUID(as_uuid=True), primary_key=True),
    Column("staff_id", PgUUID(as_uuid=True), ForeignKey("staff.id"), nullable=False),
    Column("changed_by", PgUUID(as_uuid=True), ForeignKey("staff.id")),  # NULL = 오프라인 초기 생성
    Column("at", DateTime(timezone=True), nullable=False),
    Column("before_roles", JSONB, nullable=False),
    Column("after_roles", JSONB, nullable=False),
    Column("before_active", Boolean),
    Column("after_active", Boolean, nullable=False),
    Column("reason", Text, nullable=False),
    *_timestamps(),
)

auth_sessions = Table(
    "auth_sessions", metadata,
    Column("id", PgUUID(as_uuid=True), primary_key=True),
    Column("staff_id", PgUUID(as_uuid=True), ForeignKey("staff.id"), nullable=False),
    Column("token_hash", Text, nullable=False, unique=True),
    Column("last_activity_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("revoked_at", DateTime(timezone=True)),
    *_timestamps(),
)

access_logs = Table(
    "access_logs", metadata,
    Column("id", PgUUID(as_uuid=True), primary_key=True),
    Column("sequence_no", BigInteger, nullable=False, unique=True),
    Column("at", DateTime(timezone=True), nullable=False),
    Column("actor_id", PgUUID(as_uuid=True), ForeignKey("staff.id")),
    Column("actor_label", Text, nullable=False),
    Column("client_ip", Text, nullable=False),
    Column("action", Text, nullable=False),
    Column("subject_ref", Text),
    Column("target_type", Text, nullable=False),
    Column("detail_count", Integer),
    Column("outcome", Text, nullable=False),
    Column("prev_hash", Text, nullable=False),
    Column("hash", Text, nullable=False),
    *_timestamps(),
)

access_log_reviews = Table(
    "access_log_reviews", metadata,
    Column("id", PgUUID(as_uuid=True), primary_key=True),
    Column("reviewer_id", PgUUID(as_uuid=True), ForeignKey("staff.id"), nullable=False),
    Column("reviewed_at", DateTime(timezone=True), nullable=False),
    Column("period_start", DateTime(timezone=True), nullable=False),
    Column("period_end", DateTime(timezone=True), nullable=False),
    Column("last_sequence", BigInteger, nullable=False),
    Column("last_hash", Text, nullable=False),
    Column("chain_ok", Boolean, nullable=False),
    Column("bulk_alerts", Integer, nullable=False),
    Column("note", Text, nullable=False),
    *_timestamps(),
)
