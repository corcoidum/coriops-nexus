"""장부 결과 표기(TA#2(L), H#1)와 Sydney 표기를 구조화한다. 임상 의미는 해석하지 않는다."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

import yaml


DEFAULT_CONFIG = Path(__file__).resolve().parents[3] / "config" / "result_codes.yaml"
# 코드 / #개수 / (modifier/modifier). 쉼표로 여러 결과를 잇는다.
ITEM = re.compile(r"^(?P<code>[A-Za-z][A-Za-z.]{0,29})(?:#(?P<count>[1-9]\d?))?(?:\((?P<mods>[A-Za-z]{1,5}(?:/[A-Za-z]{1,5}){0,3})\))?$")
SYDNEY_ITEM = re.compile(r"^(?P<key>[A-Za-z]{1,5})(?P<grade>[-+]{1,3})$")
MAX_FINDINGS = 10


class NotationError(ValueError):
    """사용자에게 보여줄 수 있는 형식 오류. 입력 원문을 담지 않는다."""


@dataclass(frozen=True)
class Finding:
    code: str
    lesion_count: int | None
    modifiers: tuple[str, ...]
    registered: bool

    def display(self) -> str:
        text = self.code + (f"#{self.lesion_count}" if self.lesion_count else "")
        return text + (f"({'/'.join(self.modifiers)})" if self.modifiers else "")


@dataclass(frozen=True)
class ResultCodeBook:
    """config/result_codes.yaml 등록 코드. 의미·중요도(Q19)는 여기서 사용하지 않는다."""

    codes: dict[str, str]  # 장부 표기 → 등록 코드
    modifiers: frozenset[str]
    sydney_fields: dict[str, str]
    sydney_grades: dict[str, str]

    @classmethod
    def load(cls, path: Path | None = None) -> ResultCodeBook:
        with open(path or DEFAULT_CONFIG, encoding="utf-8") as source:
            raw = yaml.safe_load(source)
        codes = {}
        for code, meta in raw["codes"].items():
            codes[code] = code
            if meta and meta.get("ledger_notation"):
                codes[meta["ledger_notation"]] = code
        return cls(
            codes=codes,
            modifiers=frozenset(raw["modifiers"]),
            sydney_fields=dict(raw["sydney_notation"]),
            sydney_grades=dict(raw["sydney_grades"]),
        )

    def parse_findings(self, notation: str) -> tuple[Finding, ...]:
        parts = [part.strip() for part in notation.split(",")]
        if not notation.strip() or any(not part for part in parts):
            raise NotationError("결과를 'TA#2(L), H#1'처럼 코드로 입력해 주세요.")
        if len(parts) > MAX_FINDINGS:
            raise NotationError(f"결과 코드는 {MAX_FINDINGS}개까지 입력할 수 있습니다.")
        findings = []
        for part in parts:
            match = ITEM.match(part)
            if not match:
                # 문장형 소견·원문 붙여넣기를 막는다(A11).
                raise NotationError("코드#개수(보조표기) 형식만 입력할 수 있습니다. 예: TA#2(L), CAG#1(im)")
            raw_code = match["code"]
            code = self.codes.get(raw_code, raw_code)
            mods = tuple(match["mods"].split("/")) if match["mods"] else ()
            findings.append(Finding(
                code=code,
                lesion_count=int(match["count"]) if match["count"] else None,
                modifiers=mods,
                # 미등록 코드·보조표기는 거부하지 않고 약어 사전(Q19) 검토 대상으로 표시한다.
                registered=raw_code in self.codes and all(m in self.modifiers for m in mods),
            ))
        return tuple(findings)

    def parse_sydney(self, notation: str) -> dict[str, str]:
        """HP-/Neu++/Mon++/Atr+/IM- → {h_pylori: NEG, neutrophil: POS2, ...}. 미기재 항목은 넣지 않는다."""
        grades: dict[str, str] = {}
        for part in notation.split("/"):
            match = SYDNEY_ITEM.match(part.strip())
            field = self.sydney_fields.get(match["key"]) if match else None
            grade = self.sydney_grades.get(match["grade"]) if match else None
            if not field or not grade or field in grades:
                raise NotationError("Sydney 등급은 'HP-/Neu++/Mon++/Atr+/IM-' 형식으로 입력해 주세요.")
            grades[field] = grade
        return grades

    def format_sydney(self, grades: dict[str, str]) -> str:
        keys = {field: key for key, field in self.sydney_fields.items()}
        signs = {grade: sign for sign, grade in self.sydney_grades.items()}
        return "/".join(keys[f] + signs[grades[f]] for f in self.sydney_fields.values() if f in grades)
