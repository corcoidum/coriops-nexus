"""백업 리허설의 새 합성 DB에만 접수·결과·계정·접속기록을 만든다."""

from datetime import date, datetime, timezone
import os

from sqlalchemy import create_engine

from app.kernel.access_log import AccessLogger
from app.kernel.auth import AuthService
from app.ledger_server import migrate
from app.modules.endoscopy_pathology.ledger_db import database_url
from app.modules.screening_lab.dashboard import LabDashboardService
from app.modules.screening_lab.store import PostgresLabStore


class FixedClock:
    def now(self):
        return datetime(2026, 11, 5, 1, tzinfo=timezone.utc)


def main():
    if os.environ.get("CORIOPS_BACKUP_REHEARSAL") != "1" or os.environ.get("PGDATABASE") != "coriops_backup_demo":
        raise SystemExit("SYNTHETIC_BACKUP_DB_REQUIRED")
    migrate()
    engine = create_engine(database_url())
    clock = FixedClock()
    staff = AuthService(engine, clock).create_staff("backup-check", "테스트백업직원", ["ADMIN"], os.environ["PGPASSWORD"],
        changed_by=None, reason="합성 백업 리허설", must_change_password=False)
    lab = LabDashboardService(clock=clock, store=PostgresLabStore(engine))
    with lab.transaction():
        case_id = lab.register(chart_no="T-BACKUP0001", patient_name="테스트백업", received_date=date(2026, 11, 5),
                               exam_kinds=["일반검진6종"], registered_by="backup-check")
        lab.enter_result(case_id, report_ref="TEST-BACKUP-0001", report_date=date(2026, 11, 5),
            rows=[("AST", "52", "H")], qualitative={}, no_flagged=False, entered_by="backup-check")
        AccessLogger(engine, clock).record(actor_id=staff, actor_label="backup-check", client_ip="127.0.0.1",
            action="CREATE", target_type="backup_rehearsal", subjects=["T-BACKUP0001"])
    engine.dispose()
    print("SYNTHETIC_SEED_OK")


if __name__ == "__main__":
    main()
