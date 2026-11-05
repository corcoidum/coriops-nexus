#!/bin/sh
# 암호문만 파일에 쓴다. 복원은 비어 있는 합성 검증 DB에만 허용한다.
set -eu
set -o pipefail
umask 077
unset PGSERVICE PGSERVICEFILE PGHOSTADDR PGOPTIONS
: "${PGHOST:?PGHOST가 필요합니다}"
: "${PGDATABASE:?PGDATABASE가 필요합니다}"
: "${PGUSER:?PGUSER가 필요합니다}"
export PGCONNECT_TIMEOUT="${PGCONNECT_TIMEOUT:-10}"
case "$PGDATABASE" in *[!A-Za-z0-9_]*|'') echo 'DB_NAME_INVALID' >&2; exit 2;; esac

case "${1:-}" in
  backup)
    : "${CORIOPS_BACKUP_RECIPIENT:?공개 recipient가 필요합니다}"
    [ -d /backups ] && [ ! -L /backups ] || exit 2
    target=$(mktemp "/backups/coriops_$(date -u +%Y%m%dT%H%M%SZ)_XXXXXXXX")
    trap 'rm -f "$target"' EXIT
    trap 'exit 1' HUP INT TERM
    pg_dump --format=custom --no-owner --no-privileges | age -r "$CORIOPS_BACKUP_RECIPIENT" > "$target"
    final="$target.age"
    mv "$target" "$final"
    sha256sum "$final" > "$final.sha256"
    basename "$final"
    ;;
  restore-test)
    [ "${CORIOPS_ALLOW_SYNTHETIC_RESTORE:-}" = 1 ] || { echo 'RESTORE_NOT_ALLOWED' >&2; exit 2; }
    case "$PGDATABASE" in *_restore_test) ;; *) echo 'RESTORE_TEST_DB_REQUIRED' >&2; exit 2;; esac
    input=${2:-}
    case "$input" in coriops_*.age) ;; *) echo 'BACKUP_NAME_INVALID' >&2; exit 2;; esac
    [ "$input" = "$(basename "$input")" ] && [ -f "/backups/$input" ] && [ ! -L "/backups/$input" ] || exit 2
    identity=${AGE_IDENTITY_PATH:-/keys/identity.key}
    identity=$(readlink -f "$identity")
    case "$identity" in /keys/*.key) ;; *) exit 2;; esac
    [ -f "$identity" ] && [ ! -L "$identity" ] || exit 2
    objects=$(psql -Atqc "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname NOT LIKE 'pg_%' AND n.nspname <> 'information_schema' AND c.relkind IN ('r','p','v','m','S')")
    [ "$objects" = 0 ] || { echo 'RESTORE_TARGET_NOT_EMPTY' >&2; exit 2; }
    # 동일한 암호문 사본의 인증을 먼저 끝낸다. 실패한 스트림으로 DB를 확정하지 않는다.
    sealed=$(mktemp /tmp/coriops-restore.XXXXXXXX)
    trap 'rm -f "$sealed"' EXIT
    trap 'exit 1' HUP INT TERM
    cp "/backups/$input" "$sealed"
    age -d -i "$identity" "$sealed" > /dev/null
    age -d -i "$identity" "$sealed" | pg_restore --dbname="$PGDATABASE" --exit-on-error --single-transaction --no-owner --no-privileges
    echo RESTORE_OK
    ;;
  *) echo 'USE: backup | restore-test BACKUP_NAME' >&2; exit 2;;
esac
