"""복원된 합성 업무 기록과 접속기록 해시 체인을 검증한다. 값·이름은 출력하지 않는다."""

import json
import os

from sqlalchemy import create_engine

from app.kernel.access_log import AccessLogger
from app.modules.endoscopy_pathology.ledger_db import database_url
from app.modules.screening_lab.dashboard import LabDashboardService
from app.modules.screening_lab.store import PostgresLabStore


def main():
    if os.environ.get("CORIOPS_BACKUP_REHEARSAL") != "1" or os.environ.get("PGDATABASE") != "coriops_restore_test":
        raise SystemExit("SYNTHETIC_RESTORE_DB_REQUIRED")
    engine = create_engine(database_url())
    cases = LabDashboardService(store=PostgresLabStore(engine)).snapshot()["cases"]
    chain = AccessLogger(engine).verify()
    preserved = (len(cases) == 1 and cases[0].record.chart_no == "T-BACKUP0001"
                 and cases[0].stage == "CHECK_PENDING" and cases[0].result_entered_by == "backup-check"
                 and cases[0].record.items[0].value == "52")
    report = {"lab_rows": len(cases), "business_preserved": preserved,
              "access_chain_ok": chain["ok"], "access_rows": chain["count"]}
    print(json.dumps(report))
    engine.dispose()
    return 0 if preserved and chain["ok"] and chain["count"] > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
