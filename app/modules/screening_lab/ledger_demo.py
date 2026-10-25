"""로그인·실자료 입력 없이 합성 혈액검체 장부를 생성하는 실행점."""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from .ledger import LabItem, LabRecord, load_policy, merge_records, new_workbook, save_new_workbook


# 아래 번호·이름·수치·H/L·위급치 표시는 모두 가짜이며 임상 기준을 뜻하지 않는다.
SYNTHETIC_RECORDS = (
    ("일반검진6종",), ("일반검진9종",), ("일반검진9종", "간검진(AFP)"),
    ("일반검진6종", "추가b형간염"), ("일반검진9종", "추가c형간염"), ("간검진(AFP)",),
    ("일반검진6종",), ("일반검진9종", "추가b형간염", "추가c형간염"), ("일반검진6종",), ("일반검진9종",),
)
SYNTHETIC_ITEMS = (
    (LabItem("Hb", "13.8"), LabItem("Glu", "92")),
    (LabItem("AST", "52", "H"), LabItem("ALT", "38")),
    (LabItem("HDL", "31", "L"), LabItem("TG", "120")),
    (LabItem("AST", "48", "H"), LabItem("GGT", "61", "H")),
    (LabItem("Glu", "999", "H", critical=True),),
    (),  # 결과 미수신 예시: 결과란 빈칸
    (LabItem("Hb", "9.8", "L"),),
    (LabItem("CHOL", "180"), LabItem("LDL", "110")),
    (LabItem("Hb", "5.1", "L", critical=True), LabItem("HDL", "33", "L")),
    (LabItem("TG", "280", "H"), LabItem("Cr", "0.9")),
)


def synthetic_records() -> list[LabRecord]:
    return [
        LabRecord(
            report_ref=f"TEST-L{number:05}", chart_no=f"{number + 9000:08}",
            patient_name=f"테스트수진자{number}", received_date=date(2026, 10, 19),
            sex="F" if number % 2 else "M", age=str(40 + number),
            exam_kinds=kinds, entrusted_date=date(2026, 10, 19), report_date=date(2026, 10, 21),
            items=items,
        )
        for number, (kinds, items) in enumerate(zip(SYNTHETIC_RECORDS, SYNTHETIC_ITEMS, strict=True), 1)
    ]


def main() -> int:
    """원본을 덮어쓰지 않고 합성 결과 10건을 새 파일에 쓴다."""
    parser = argparse.ArgumentParser(description="합성 데이터 전용 혈액검체 Excel 시연")
    parser.add_argument("--output", required=True, type=Path)
    options = parser.parse_args()
    policy = load_policy()
    workbook = new_workbook(policy)
    records = synthetic_records()
    summary = merge_records(workbook, records, policy)
    repeated = merge_records(workbook, records, policy, fingerprints=summary.fingerprints)
    try:
        save_new_workbook(workbook, options.output)
    except FileExistsError:
        print("OUTPUT_EXISTS: 기존 파일을 보존했습니다. 다른 새 출력 경로를 지정하세요.")
        return 2
    finally:
        workbook.close()
    critical = sum(issue.code == "CRITICAL_REPORT" for issue in summary.issues)
    print(f"합성 행 {summary.appended}개, 재실행 중복 추가 {repeated.appended}개, 원장 보고 대상(위급치) {critical}건")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
