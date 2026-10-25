"""개인 계정 로그인·세션·권한. 업무 모듈을 알지 못하며 config/security.yaml 값을 따른다.

- 비밀번호: argon2id 해시만 저장, 10자 이상, 아이디 포함 금지
- 잠금: 연속 5회 실패 → 30분
- 세션: 서버 저장(토큰은 SHA-256만 저장), 15분 미사용 또는 12시간 경과 시 종료
- 권한 변경·비활성화·비밀번호 초기화: 대상의 모든 세션 즉시 폐기 + 권한 이력
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path
import re
import secrets
from uuid import UUID, uuid4

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import delete, insert, select, update
from sqlalchemy.engine import Engine
import yaml

from app.kernel.clock import Clock, SystemClock
from app.kernel.security_db import ROLES, auth_sessions, permission_history, staff, staff_roles


DEFAULT_CONFIG = Path(__file__).resolve().parents[2] / "config" / "security.yaml"
USERNAME = re.compile(r"^[a-z0-9._-]{3,30}$")
ROLE_LABELS = {"DOCTOR": "원장", "ADMIN": "원무", "NURSE": "간호", "PRIVACY_OFFICER": "개인정보 책임자"}


class AuthError(Exception):
    """화면에 보여줄 수 있는 메시지. 아이디·비밀번호 원문을 담지 않는다."""

    def __init__(self, message: str, code: str, status_code: int = 400, staff_id: UUID | None = None):
        self.message, self.code, self.status_code, self.staff_id = message, code, status_code, staff_id
        super().__init__(message)


@dataclass(frozen=True)
class AuthPolicy:
    min_password_length: int
    failed_login_limit: int
    lockout_minutes: int
    idle_minutes: int
    absolute_hours: int
    cookie_secure: bool
    permissions: dict[str, frozenset[str]]

    @classmethod
    def load(cls, path: Path | None = None) -> AuthPolicy:
        with open(path or DEFAULT_CONFIG, encoding="utf-8") as source:
            raw = yaml.safe_load(source)["authentication"]
        return cls(
            min_password_length=int(raw["minimum_password_length"]), failed_login_limit=int(raw["failed_login_limit"]),
            lockout_minutes=int(raw["lockout_minutes"]), idle_minutes=int(raw["idle_timeout_minutes"]),
            absolute_hours=int(raw["session_absolute_hours"]), cookie_secure=bool(raw["cookies"]["secure"]),
            permissions={name: frozenset(roles) for name, roles in raw["permissions"].items()},
        )


@dataclass(frozen=True)
class Actor:
    """요청을 보낸 사람. 시연 모드에서는 staff_id가 없는 합성 사용자다."""

    staff_id: UUID | None
    username: str
    display_name: str
    roles: frozenset[str]
    csrf_token: str
    permissions: dict[str, frozenset[str]] = field(default_factory=dict, repr=False)
    must_change_password: bool = False
    demo: bool = False

    def can(self, permission: str) -> bool:
        if self.demo:
            return True
        return bool(self.roles & self.permissions.get(permission, frozenset()))

    @property
    def label(self) -> str:
        return self.username

    @property
    def role_labels(self) -> str:
        return "·".join(ROLE_LABELS[r] for r in ROLES if r in self.roles)


@dataclass(frozen=True)
class StaffSummary:
    id: UUID
    username: str
    display_name: str
    active: bool
    roles: frozenset[str]
    locked: bool
    must_change_password: bool


def csrf_for(token: str) -> str:
    """세션 토큰에서 CSRF 값을 만든다. 쿠키(HttpOnly)를 모르면 계산할 수 없다."""
    return sha256(b"csrf:" + token.encode()).hexdigest()


def _token_hash(token: str) -> str:
    return sha256(token.encode()).hexdigest()


class AuthService:
    def __init__(self, engine: Engine, clock: Clock | None = None, policy: AuthPolicy | None = None):
        self._engine = engine
        self._clock = clock or SystemClock()
        self.policy = policy or AuthPolicy.load()
        self._hasher = PasswordHasher()  # argon2id
        self._dummy_hash = self._hasher.hash(secrets.token_urlsafe(16))

    # ---------- 공통

    def _check_password(self, password: str, username: str) -> None:
        if len(password) < self.policy.min_password_length:
            raise AuthError(f"비밀번호는 {self.policy.min_password_length}자 이상이어야 합니다.", "WEAK_PASSWORD", 422)
        if username and username in password.lower():
            raise AuthError("비밀번호에 아이디를 넣을 수 없습니다.", "WEAK_PASSWORD", 422)

    @staticmethod
    def _check_roles(roles) -> frozenset[str]:
        chosen = frozenset(roles)
        if not chosen or not chosen <= set(ROLES):
            raise AuthError("역할을 하나 이상 선택해 주세요.", "INVALID_ROLES", 422)
        return chosen

    def _roles(self, connection, staff_id: UUID) -> frozenset[str]:
        rows = connection.execute(select(staff_roles.c.role).where(staff_roles.c.staff_id == staff_id))
        return frozenset(row.role for row in rows)

    def _history(self, connection, staff_id, changed_by, before_roles, after_roles, before_active, after_active,
                 reason: str, now: datetime) -> None:
        connection.execute(insert(permission_history).values(
            id=uuid4(), staff_id=staff_id, changed_by=changed_by, at=now, before_roles=sorted(before_roles),
            after_roles=sorted(after_roles), before_active=before_active, after_active=after_active, reason=reason,
            created_at=now, updated_at=now))

    def _revoke_all(self, connection, staff_id: UUID, now: datetime) -> None:
        connection.execute(update(auth_sessions).where(auth_sessions.c.staff_id == staff_id,
                                                       auth_sessions.c.revoked_at.is_(None))
                           .values(revoked_at=now, updated_at=now))

    @staticmethod
    def _reason(reason: str) -> str:
        clean = reason.strip()
        if not clean or len(clean) > 120:
            raise AuthError("변경 사유를 1~120자로 입력해 주세요.", "REASON_REQUIRED", 422)
        return clean

    def _privacy_officers(self, connection, excluding: UUID | None = None) -> int:
        query = (select(staff.c.id).join(staff_roles, staff_roles.c.staff_id == staff.c.id)
                 .where(staff.c.active.is_(True), staff_roles.c.role == "PRIVACY_OFFICER"))
        return sum(1 for row in connection.execute(query) if row.id != excluding)

    # ---------- 계정

    def has_any_staff(self) -> bool:
        with self._engine.connect() as connection:
            return connection.execute(select(staff.c.id).limit(1)).first() is not None

    def create_staff(self, username: str, display_name: str, roles, password: str, *, changed_by: UUID | None,
                     reason: str, must_change_password: bool = True) -> UUID:
        username = username.strip().lower()
        if not USERNAME.match(username):
            raise AuthError("아이디는 영문 소문자·숫자·._- 3~30자로 입력해 주세요.", "INVALID_USERNAME", 422)
        name = display_name.strip()
        if not name or len(name) > 30:
            raise AuthError("표시 이름을 1~30자로 입력해 주세요.", "INVALID_NAME", 422)
        chosen = self._check_roles(roles)
        self._check_password(password, username)
        reason = self._reason(reason)
        now = self._clock.now()
        staff_id = uuid4()
        with self._engine.begin() as connection:
            if connection.execute(select(staff.c.id).where(staff.c.username == username)).first():
                raise AuthError("이미 있는 아이디입니다.", "DUPLICATE_USERNAME", 409)
            connection.execute(insert(staff).values(
                id=staff_id, username=username, display_name=name, password_hash=self._hasher.hash(password),
                active=True, must_change_password=must_change_password, failed_login_count=0, locked_until=None,
                created_at=now, updated_at=now))
            for role in sorted(chosen):
                connection.execute(insert(staff_roles).values(id=uuid4(), staff_id=staff_id, role=role,
                                                              created_at=now, updated_at=now))
            self._history(connection, staff_id, changed_by, (), chosen, None, True, reason, now)
        return staff_id

    def list_staff(self) -> list[StaffSummary]:
        now = self._clock.now()
        with self._engine.connect() as connection:
            rows = connection.execute(select(staff).order_by(staff.c.username)).all()
            return [StaffSummary(r.id, r.username, r.display_name, r.active, self._roles(connection, r.id),
                                 bool(r.locked_until and r.locked_until > now), r.must_change_password) for r in rows]

    def set_roles(self, target: UUID, roles, *, by: Actor, reason: str) -> None:
        chosen = self._check_roles(roles)
        reason = self._reason(reason)
        now = self._clock.now()
        with self._engine.begin() as connection:
            row = connection.execute(select(staff).where(staff.c.id == target).with_for_update()).first()
            if row is None:
                raise AuthError("계정을 찾을 수 없습니다.", "NOT_FOUND", 404)
            before = self._roles(connection, target)
            if target == by.staff_id and before - chosen:
                raise AuthError("자기 자신의 역할은 줄일 수 없습니다. 다른 책임자에게 요청해 주세요.", "SELF_CHANGE", 403)
            if "PRIVACY_OFFICER" in before and "PRIVACY_OFFICER" not in chosen and not self._privacy_officers(
                    connection, excluding=target):
                raise AuthError("마지막 개인정보 책임자의 역할은 뺄 수 없습니다.", "LAST_OFFICER", 409)
            connection.execute(delete(staff_roles).where(staff_roles.c.staff_id == target))
            for role in sorted(chosen):
                connection.execute(insert(staff_roles).values(id=uuid4(), staff_id=target, role=role,
                                                              created_at=now, updated_at=now))
            connection.execute(update(staff).where(staff.c.id == target).values(updated_at=now))
            self._history(connection, target, by.staff_id, before, chosen, row.active, row.active, reason, now)
            self._revoke_all(connection, target, now)

    def set_active(self, target: UUID, active: bool, *, by: Actor, reason: str) -> None:
        reason = self._reason(reason)
        now = self._clock.now()
        with self._engine.begin() as connection:
            row = connection.execute(select(staff).where(staff.c.id == target).with_for_update()).first()
            if row is None:
                raise AuthError("계정을 찾을 수 없습니다.", "NOT_FOUND", 404)
            if not active and target == by.staff_id:
                raise AuthError("자기 계정은 비활성화할 수 없습니다.", "SELF_CHANGE", 403)
            roles = self._roles(connection, target)
            if not active and "PRIVACY_OFFICER" in roles and not self._privacy_officers(connection, excluding=target):
                raise AuthError("마지막 개인정보 책임자는 비활성화할 수 없습니다.", "LAST_OFFICER", 409)
            connection.execute(update(staff).where(staff.c.id == target).values(active=active, updated_at=now))
            self._history(connection, target, by.staff_id, roles, roles, row.active, active, reason, now)
            self._revoke_all(connection, target, now)

    def reset_password(self, target: UUID, temporary: str, *, by: Actor, reason: str) -> None:
        reason = self._reason(reason)
        now = self._clock.now()
        with self._engine.begin() as connection:
            row = connection.execute(select(staff).where(staff.c.id == target).with_for_update()).first()
            if row is None:
                raise AuthError("계정을 찾을 수 없습니다.", "NOT_FOUND", 404)
            self._check_password(temporary, row.username)
            connection.execute(update(staff).where(staff.c.id == target).values(
                password_hash=self._hasher.hash(temporary), must_change_password=True, failed_login_count=0,
                locked_until=None, updated_at=now))
            roles = self._roles(connection, target)
            self._history(connection, target, by.staff_id, roles, roles, row.active, row.active,
                          f"비밀번호 초기화: {reason}", now)
            self._revoke_all(connection, target, now)

    # ---------- 로그인·세션

    def login(self, username: str, password: str) -> tuple[Actor, str]:
        """성공하면 (사용자, 세션 토큰). 실패 메시지는 아이디 존재 여부를 드러내지 않는다."""
        now = self._clock.now()
        username = username.strip().lower()[:30]
        with self._engine.begin() as connection:
            row = connection.execute(select(staff).where(staff.c.username == username).with_for_update()).first()
            if row is None:
                # 없는 아이디도 같은 시간이 걸리게 해시를 한 번 검증한다.
                try:
                    self._hasher.verify(self._dummy_hash, password)
                except (VerificationError, InvalidHashError):
                    pass
                raise AuthError("아이디 또는 비밀번호가 맞지 않습니다.", "INVALID", 401)
            if row.locked_until and row.locked_until > now:
                raise AuthError(f"로그인 실패가 많아 잠겼습니다. {self.policy.lockout_minutes}분 뒤 다시 시도해 주세요.",
                                "LOCKED", 423, row.id)
            try:
                self._hasher.verify(row.password_hash, password)
            except (VerificationError, InvalidHashError):
                failures = row.failed_login_count + 1
                locked = now + timedelta(minutes=self.policy.lockout_minutes) \
                    if failures >= self.policy.failed_login_limit else None
                connection.execute(update(staff).where(staff.c.id == row.id).values(
                    failed_login_count=0 if locked else failures, locked_until=locked, updated_at=now))
                # 실패 횟수는 저장(commit)한 뒤에 오류를 올린다. 트랜잭션 안에서 올리면 횟수가 되돌려진다.
                failure = AuthError("아이디 또는 비밀번호가 맞지 않습니다.", "LOCKED_NOW" if locked else "INVALID",
                                    401, row.id)
            else:
                failure = None
        if failure:
            raise failure
        with self._engine.begin() as connection:
            row = connection.execute(select(staff).where(staff.c.id == row.id).with_for_update()).first()
            if row.locked_until and row.locked_until > now:  # 두 트랜잭션 사이에 잠긴 경우
                raise AuthError(f"로그인 실패가 많아 잠겼습니다. {self.policy.lockout_minutes}분 뒤 다시 시도해 주세요.",
                                "LOCKED", 423, row.id)
            if not row.active:
                raise AuthError("사용이 중지된 계정입니다. 개인정보 책임자에게 문의해 주세요.", "INACTIVE", 403, row.id)
            connection.execute(update(staff).where(staff.c.id == row.id).values(
                failed_login_count=0, locked_until=None, updated_at=now))
            token = secrets.token_urlsafe(32)
            connection.execute(insert(auth_sessions).values(
                id=uuid4(), staff_id=row.id, token_hash=_token_hash(token), last_activity_at=now,
                expires_at=now + timedelta(hours=self.policy.absolute_hours), revoked_at=None,
                created_at=now, updated_at=now))
            actor = Actor(row.id, row.username, row.display_name, self._roles(connection, row.id), csrf_for(token),
                          self.policy.permissions, row.must_change_password)
        return actor, token

    def resolve(self, token: str) -> Actor | None:
        """쿠키 토큰으로 사용자를 찾는다. 미사용·만료·폐기·비활성 계정이면 None."""
        if not token or len(token) > 100:
            return None
        now = self._clock.now()
        with self._engine.begin() as connection:
            session = connection.execute(select(auth_sessions).where(
                auth_sessions.c.token_hash == _token_hash(token)).with_for_update()).first()
            if session is None or session.revoked_at is not None:
                return None
            idle = now - session.last_activity_at > timedelta(minutes=self.policy.idle_minutes)
            row = connection.execute(select(staff).where(staff.c.id == session.staff_id)).first()
            if idle or now >= session.expires_at or not row.active:
                connection.execute(update(auth_sessions).where(auth_sessions.c.id == session.id)
                                   .values(revoked_at=now, updated_at=now))
                return None
            connection.execute(update(auth_sessions).where(auth_sessions.c.id == session.id)
                               .values(last_activity_at=now, updated_at=now))
            return Actor(row.id, row.username, row.display_name, self._roles(connection, row.id), csrf_for(token),
                         self.policy.permissions, row.must_change_password)

    def logout(self, token: str) -> None:
        now = self._clock.now()
        with self._engine.begin() as connection:
            connection.execute(update(auth_sessions).where(auth_sessions.c.token_hash == _token_hash(token),
                                                           auth_sessions.c.revoked_at.is_(None))
                               .values(revoked_at=now, updated_at=now))

    def change_password(self, actor: Actor, current: str, new: str, token: str) -> None:
        now = self._clock.now()
        with self._engine.begin() as connection:
            row = connection.execute(select(staff).where(staff.c.id == actor.staff_id).with_for_update()).first()
            try:
                self._hasher.verify(row.password_hash, current)
            except (VerificationError, InvalidHashError):
                raise AuthError("현재 비밀번호가 맞지 않습니다.", "INVALID", 422) from None
            if current == new:
                raise AuthError("새 비밀번호는 현재 비밀번호와 달라야 합니다.", "WEAK_PASSWORD", 422)
            self._check_password(new, row.username)
            connection.execute(update(staff).where(staff.c.id == row.id).values(
                password_hash=self._hasher.hash(new), must_change_password=False, updated_at=now))
            # 다른 PC에 남은 세션은 끊고 지금 세션만 유지한다.
            connection.execute(update(auth_sessions).where(
                auth_sessions.c.staff_id == row.id, auth_sessions.c.revoked_at.is_(None),
                auth_sessions.c.token_hash != _token_hash(token)).values(revoked_at=now, updated_at=now))
