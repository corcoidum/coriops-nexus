"""전용 Compose 프로젝트의 합성 DB만 만들고 암호화·거부·복원을 검증한다."""

import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import tempfile
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    project = "coriops-backup-check-" + uuid4().hex[:10]
    base = (ROOT / "outputs" / "backup-rehearsal").resolve()
    base.relative_to(ROOT.resolve())
    base.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(dir=base)).resolve()
    work.relative_to(base)
    keys, archive = work / "keys", work / "archives"
    keys.mkdir()
    archive.mkdir()
    env = dict(os.environ, CORIOPS_BACKUP_TEST_PASSWORD=secrets.token_hex(24),
               CORIOPS_BACKUP_TEST_KEYS=str(keys), CORIOPS_BACKUP_TEST_DIR=str(archive),
               # Linux bind mount의 소유자와 맞춘다. Docker Desktop은 호스트 UID가 없다.
               CORIOPS_BACKUP_TEST_UID=str(getattr(os, "getuid", lambda: 0)()),
               CORIOPS_BACKUP_TEST_GID=str(getattr(os, "getgid", lambda: 0)()))
    command = ["docker", "compose", "-p", project, "-f", str(ROOT / "docker-compose.backup-test.yml")]
    def run(*args, success=True, expected_error=None):
        result = subprocess.run([*command, *args], cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8")
        if success and result.returncode:
            # 명령 인수 대신 비밀값을 가린 마지막 진단 한 줄만 남긴다.
            diagnostics = [line for line in result.stderr.strip().splitlines()
                           if "report unexpected or unhelpful errors" not in line]
            detail = diagnostics[-1] if diagnostics else "NO_DIAGNOSTIC"
            detail = detail.replace(env["CORIOPS_BACKUP_TEST_PASSWORD"], "[redacted]")
            if "AGE-SECRET-KEY" in detail:
                detail = "KEY_DIAGNOSTIC_REDACTED"
            raise RuntimeError("BACKUP_REHEARSAL_STEP_FAILED: " + args[0] + ": " + detail[:300])
        if not success and result.returncode == 0:
            raise RuntimeError("BACKUP_REHEARSAL_EXPECTED_REJECTION")
        if expected_error and expected_error not in result.stderr + result.stdout:
            raise RuntimeError("BACKUP_REHEARSAL_UNEXPECTED_REJECTION")
        return result.stdout.strip()
    try:
        run("build", "keys")
        run("up", "-d", "--wait", "source", "restore")
        run("run", "--rm", "keys")
        run("run", "--rm", "keys", "age-keygen", "-o", "/keys/wrong.key")
        env["CORIOPS_BACKUP_TEST_RECIPIENT"] = run("run", "--rm", "keys", "age-keygen", "-y", "/keys/identity.key")
        run("run", "--rm", "check")
        filename = run("run", "--rm", "archive", "backup").splitlines()[-1]
        sealed = archive / filename
        if sealed.parent != archive or sealed.suffix != ".age" or not sealed.is_file():
            raise RuntimeError("BACKUP_REHEARSAL_OUTPUT_INVALID")
        data = sealed.read_bytes()
        if not data.startswith(b"age-encryption.org/v1\n") or b"T-BACKUP0001" in data:
            raise RuntimeError("BACKUP_REHEARSAL_NOT_ENCRYPTED")
        restore = ["run", "--rm", "-e", "PGHOST=restore", "-e", "PGDATABASE=coriops_restore_test"]
        run(*restore, "-e", "CORIOPS_ALLOW_SYNTHETIC_RESTORE=0", "archive", "restore-test", filename,
            success=False, expected_error="RESTORE_NOT_ALLOWED")
        run("run", "--rm", "archive", "restore-test", filename, success=False, expected_error="RESTORE_TEST_DB_REQUIRED")
        run(*restore, "-e", "AGE_IDENTITY_PATH=/keys/wrong.key", "archive", "restore-test", filename,
            success=False, expected_error="no identity matched")
        corrupt = archive / "coriops_corrupt.age"
        modified = bytearray(data)
        modified[len(modified) // 2] ^= 1
        corrupt.write_bytes(modified)
        run(*restore, "archive", "restore-test", corrupt.name, success=False, expected_error="failed to decrypt")
        run(*restore, "archive", "restore-test", filename)
        result = json.loads(run("run", "--rm", "-e", "PGHOST=restore", "-e", "PGDATABASE=coriops_restore_test",
                                "check", "python", "-m", "scripts.backup_check").splitlines()[-1])
        run(*restore, "archive", "restore-test", filename, success=False, expected_error="RESTORE_TARGET_NOT_EMPTY")
        result.update(encrypted=True, wrong_key_rejected=True, tamper_rejected=True, nonempty_target_rejected=True,
                      explicit_restore_opt_in=True, synthetic_database_guard=True)
        print(json.dumps(result))
        return 0
    finally:
        try:
            run("down", "--timeout", "5")
        finally:
            # 삭제 직전 실제 절대 경로가 이번 리허설 디렉터리 안인지 다시 확인한다.
            work.resolve().relative_to(base)
            shutil.rmtree(work)


if __name__ == "__main__":
    raise SystemExit(main())
