"""로그인·실자료 입력 없이 합성 장부를 생성하는 실행점."""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from .ledger import ResultRecord, load_policy, merge_records, new_workbook, save_new_workbook


def main() -> int:
    """원본을 덮어쓰지 않고 합성 결과 세 건을 새 파일에 쓴다."""
    parser = argparse.ArgumentParser(description="합성 데이터 전용 조직검체 Excel 시연")
    parser.add_argument("--output", required=True, type=Path)
    options = parser.parse_args()
    policy = load_policy()
    workbook = new_workbook(policy)
    records = [
        ResultRecord(
            report_ref=f"TEST-{number:06}", chart_no=f"{number:08}",
            patient_name=f"테스트환자{number}", exam_date=date(2026, 10, 19),
            age="합성", sex="UNKNOWN", entrusted_date=date(2026, 10, 20),
            exam_kind="합성 검사", specimen_count=number, report_date=date(2026, 10, 22),
            site_text="합성 부위 원문", result_text="합성 결과 원문",
        )
        for number in range(1, 4)
    ]
    summary = merge_records(workbook, records, policy)
    repeated = merge_records(workbook, records, policy, fingerprints=summary.fingerprints)
    try:
        save_new_workbook(workbook, options.output)
    except FileExistsError:
        print("OUTPUT_EXISTS: 기존 파일을 보존했습니다. 다른 새 출력 경로를 지정하세요.")
        return 2
    finally:
        workbook.close()
    print(f"합성 행 {summary.appended}개, 재실행 중복 추가 {repeated.appended}개, 약어 검토 {len(summary.issues)}개")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
