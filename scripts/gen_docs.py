"""ontology/coriops.yaml → docs/ontology.md·erd.md·state-machine.md·fhir-mapping.md.

사용법:
    python scripts/gen_docs.py           # 문서를 다시 만든다
    python scripts/gen_docs.py --check   # 커밋된 문서가 YAML과 같은지만 확인한다(CI)
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import sys

import yaml


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "ontology" / "coriops.yaml"
DOCS = ROOT / "docs"
STATUS_LABELS = {"implemented": "구현됨", "planned": "예정"}
FHIR_NONE = "직접 대응 없음"


def _header(title: str, digest: str) -> str:
    return (f"# {title}\n\n> 원천: `ontology/coriops.yaml` · SHA-256 `{digest}`\n"
            "> `python scripts/gen_docs.py`가 만든 문서다. 직접 고치지 말고 YAML을 고친 뒤 다시 만든다.\n\n")


def _status(cls: dict) -> str:
    label = STATUS_LABELS[cls["status"]]
    return f"{label}(Stage {cls['planned_stage']})" if cls.get("planned_stage") else label


def _where(cls: dict) -> str:
    if "table" in cls:
        return f"테이블 `{cls['table']}`"
    if "embedded_in" in cls:
        return f"`{cls['embedded_in']}` 안의 JSONB"
    return f"등록값 `{cls['source']}`"


def _constraints(field: dict) -> str:
    skip = ("type", "nullable", "enum", "references", "relation")
    parts = []
    if "enum" in field:
        parts.append(f"enum {field['enum']}")
    if "references" in field:
        parts.append(f"FK → {field['references']}" + (f" ({field['relation']})" if "relation" in field else ""))
    parts += [f"{key}={value}" for key, value in field.items() if key not in skip]
    return "; ".join(parts) or "—"


def _field_rows(fields: dict) -> list[str]:
    rows = ["| 필드 | 타입 | NULL | 제약 |", "|---|---|---|---|"]
    rows += [f"| {name} | {f['type']} | {'허용' if f.get('nullable') else '금지'} | {_constraints(f)} |"
             for name, f in fields.items()]
    return rows


def render_ontology(y: dict, digest: str) -> str:
    lines = [_header("Ontology 데이터 사전", digest) + y["doc_text"]["ontology"].rstrip("\n"), "",
             "## 클래스 한눈에 보기", "", "| 클래스 | 위치 | 상태 | 저장 | 설명 |", "|---|---|---|---|---|"]
    lines += [f"| [{name}](#{name.lower()}) | {c['layer']} | {_status(c)} | {_where(c)} | {c['description']} |"
              for name, c in y["classes"].items()]
    lines += ["", "## 공통 필드", "", *_field_rows(y["common_fields"]), "",
              "테이블이 있는 모든 클래스에 적용한다.", "", "## 클래스", ""]
    for name, c in y["classes"].items():
        meta = f"위치 `{c['layer']}` · {_status(c)} · {_where(c)} · FHIR `{c['fhir'] or FHIR_NONE}`"
        lines += [f"### {name}", "", c["description"], "", meta + (" · 추가만 허용" if c.get("immutable") else ""),
                  "", *_field_rows(c["fields"])]
        for unique in c.get("unique", []):
            lines += ["", f"복합 UNIQUE: `{', '.join(unique)}`"]
        if c.get("constraints"):
            lines += ["", "제약: " + " / ".join(c["constraints"])]
        lines.append("")
    lines += ["## Enum", "", "| 이름 | 값 |", "|---|---|"]
    lines += [f"| {name} | {', '.join(values)} |" for name, values in y["enums"].items()]
    lines += ["", "## 등록값", "", "| 이름 | 원천 | 키 | 소유 |", "|---|---|---|---|"]
    lines += [f"| {name} | `{r['source']}` | `{r['key']}` | {r['owner']} |" for name, r in y["registries"].items()]
    lines += ["", "## 전환기 테이블", ""]
    lines += [f"- `{table}`: {note}" for table, note in y.get("transitional_tables", {}).items()] or ["없음"]
    lines += ["", "## 규칙", ""]
    lines += [f"- `{key}`: {value}" for key, value in y["conventions"].items()]
    return "\n".join(lines) + "\n"


def render_erd(y: dict, digest: str) -> str:
    tables = {name: c for name, c in y["classes"].items() if "table" in c}
    lines = [_header("ERD", digest) + y["doc_text"]["erd"].rstrip("\n"), "", "```mermaid", "erDiagram"]
    for name, c in tables.items():
        lines.append(f"    {name} {{")
        lines += ["        uuid id PK", "        timestamptz created_at", "        timestamptz updated_at"]
        lines += [f"        {f['type']} {field}" + (" FK" if "references" in f else "")
                  for field, f in c["fields"].items()]
        lines.append("    }")
    for name, c in tables.items():
        for field, f in c["fields"].items():
            if "references" in f:
                # 참조하는 쪽 기준: unique FK면 1:0..1, 아니면 N:1. NULL 허용이면 대상이 없을 수 있다.
                left = "|o" if f.get("unique") else "}o"
                right = "o|" if f.get("nullable") else "||"
                lines.append(f"    {name} {left}--{right} {f['references']} : {f.get('relation', field)}")
    lines += ["```", "", "## 단계별 테이블", "", "| 클래스 | 테이블 | 상태 |", "|---|---|---|"]
    lines += [f"| {name} | `{c['table']}` | {_status(c)} |" for name, c in tables.items()]
    return "\n".join(lines) + "\n"


def render_state_machine(y: dict, digest: str) -> str:
    w = y["workflow"]
    lines = [_header(f"{w['entity']} 단계", digest) + y["doc_text"]["state_machine"].rstrip("\n"), "",
             "## 단계 계산 순서", "", "위에서부터 처음 맞는 단계가 된다.", "",
             "| 순서 | 단계 | 조건 |", "|---|---|---|"]
    lines += [f"| {i} | {d['stage']} ({w['labels'][d['stage']]}) | {d['when']} |"
              for i, d in enumerate(w["derivation"], 1)]
    lines += ["", "```mermaid", "stateDiagram-v2"]
    lines += [f"    {t['from']} --> {t['to']} : {t['action']}" for t in w["transitions"]]
    lines += ["```", "", "## 전이 표", "", "| from | to | action | 권한 | guard |", "|---|---|---|---|---|"]
    lines += [f"| {t['from']} | {t['to']} | {t['action']} | {t['permission']} | {t['guard']} |"
              for t in w["transitions"]]
    lines += ["", "## Guard 정의", ""]
    lines += [f"- `{key}`: {value}" for key, value in w["guards"].items()]
    lines += ["", w["imports"]]
    return "\n".join(lines) + "\n"


def render_fhir(y: dict, digest: str) -> str:
    lines = [_header("FHIR 개념 대응", digest) + y["doc_text"]["fhir"].rstrip("\n"), "",
             "| 내부 클래스 | 상태 | 개념 대응 |", "|---|---|---|"]
    lines += [f"| {name} | {_status(c)} | {c['fhir'] or FHIR_NONE + ' — 내부 운영 엔티티'} |"
              for name, c in y["classes"].items()]
    return "\n".join(lines) + "\n"


def render(source: bytes) -> dict[str, str]:
    """파일 이름 → 내용. 같은 YAML이면 언제나 같은 결과를 낸다."""
    y = yaml.safe_load(source)
    digest = hashlib.sha256(source).hexdigest()
    return {
        "ontology.md": render_ontology(y, digest),
        "erd.md": render_erd(y, digest),
        "state-machine.md": render_state_machine(y, digest),
        "fhir-mapping.md": render_fhir(y, digest),
    }


def stale(docs: Path = DOCS, source: Path = SOURCE) -> list[str]:
    return [name for name, text in render(source.read_bytes()).items()
            if not (docs / name).exists() or (docs / name).read_text(encoding="utf-8") != text]


def main(argv: list[str]) -> int:
    if "--check" in argv:
        names = stale()
        if names:
            print("YAML과 다른 문서:", ", ".join(names), "→ python scripts/gen_docs.py 로 다시 만드세요.")
            return 1
        print("문서가 YAML과 같습니다.")
        return 0
    for name, text in render(SOURCE.read_bytes()).items():
        (DOCS / name).write_text(text, encoding="utf-8")
    print("문서 4개를 다시 만들었습니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
