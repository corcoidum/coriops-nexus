"""정식 모델(ontology/coriops.yaml)·코드 테이블·생성 문서가 서로 어긋나지 않는다.

DB 스키마가 코드 테이블과 같은지는 test_ledger_db의 migration 시험이 확인한다. 여기서 YAML = 코드를 확인하면
YAML = 코드 = DB가 된다.
"""

import importlib.util
from pathlib import Path
import re

import pytest
from sqlalchemy import BigInteger, Boolean, CheckConstraint, Date, DateTime, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID
import yaml

from app.kernel import security_db
from app.kernel.access_log import ACTION_LABELS
from app.modules.endoscopy_pathology import ledger_db
from app.modules.endoscopy_pathology.ledger_model import STAGE_LABELS


ROOT = Path(__file__).resolve().parents[2]
ONTOLOGY = yaml.safe_load((ROOT / "ontology" / "coriops.yaml").read_text(encoding="utf-8"))
CLASSES = ONTOLOGY["classes"]
TABLES = {table.name: table for meta in (security_db.metadata, ledger_db.metadata) for table in meta.tables.values()}
IMPLEMENTED = {name: c for name, c in CLASSES.items() if c["status"] == "implemented" and "table" in c}


def _load_generator():
    spec = importlib.util.spec_from_file_location("gen_docs", ROOT / "scripts" / "gen_docs.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _config(name: str) -> dict:
    return yaml.safe_load((ROOT / "config" / name).read_text(encoding="utf-8"))


def _type_matches(kind: str, column) -> bool:
    sql_type = column.type
    return {
        "uuid": isinstance(sql_type, PgUUID),
        "timestamptz": isinstance(sql_type, DateTime) and sql_type.timezone,
        "date": isinstance(sql_type, Date) and not isinstance(sql_type, DateTime),
        "string": isinstance(sql_type, Text),
        "enum": isinstance(sql_type, Text),
        "integer": type(sql_type) is Integer,
        "bigint": isinstance(sql_type, BigInteger),
        "boolean": isinstance(sql_type, Boolean),
        "jsonb": isinstance(sql_type, JSONB),
    }[kind]


def _check_values(table, column_name: str) -> set[str] | None:
    """`col IN ('A', 'B')` 형태의 CHECK가 있으면 그 값 집합."""
    for constraint in table.constraints:
        if isinstance(constraint, CheckConstraint):
            match = re.search(rf"\b{column_name} IN \(([^)]*)\)", str(constraint.sqltext))
            if match:
                return set(re.findall(r"'([^']*)'", match.group(1)))
    return None


def test_generated_docs_are_current():
    """YAML을 고치고 문서를 다시 만들지 않으면 실패한다(python scripts/gen_docs.py)."""
    assert _load_generator().stale() == []


def test_generator_is_deterministic():
    generator = _load_generator()
    source = (ROOT / "ontology" / "coriops.yaml").read_bytes()
    assert generator.render(source) == generator.render(source)


@pytest.mark.parametrize("name", sorted(IMPLEMENTED))
def test_implemented_class_matches_its_table(name):
    cls = IMPLEMENTED[name]
    assert cls["table"] in TABLES, f"{name}: 테이블 {cls['table']}이 코드에 없다"
    table = TABLES[cls["table"]]
    expected = {**ONTOLOGY["common_fields"], **cls["fields"]}
    assert set(table.columns.keys()) == set(expected), f"{name}: 열 목록이 다르다"
    for field_name, field in expected.items():
        column = table.columns[field_name]
        assert _type_matches(field["type"], column), f"{name}.{field_name}: 타입 {field['type']} ≠ {column.type}"
        if not field.get("primary_key"):
            assert column.nullable == bool(field.get("nullable")), f"{name}.{field_name}: NULL 허용이 다르다"
        targets = {fk.column.table.name for fk in column.foreign_keys}
        if "references" in field:
            assert targets == {CLASSES[field["references"]]["table"]}, f"{name}.{field_name}: FK 대상이 다르다"
        else:
            assert not targets, f"{name}.{field_name}: YAML에 없는 FK"
        assert bool(column.unique) == bool(field.get("unique")), f"{name}.{field_name}: UNIQUE가 다르다"
        values = _check_values(table, field_name)
        if field["type"] == "enum" and values is not None:
            assert values == set(ONTOLOGY["enums"][field["enum"]]), f"{name}.{field_name}: CHECK 값이 다르다"
        assert field["type"] == "enum" or values is None, f"{name}.{field_name}: CHECK 목록이 있으면 enum이다"
    composite = {tuple(c.columns.keys()) for c in table.constraints
                 if isinstance(c, UniqueConstraint) and len(c.columns) > 1}
    assert composite == {tuple(u) for u in cls.get("unique", [])}, f"{name}: 복합 UNIQUE가 다르다"


def test_every_code_table_is_described():
    """새 테이블을 만들면 YAML에 implemented 클래스로 적어야 한다(전환기 테이블 제외)."""
    described = {c["table"] for c in IMPLEMENTED.values()} | set(ONTOLOGY.get("transitional_tables", {}))
    assert set(TABLES) == described


def test_planned_classes_have_no_table_yet():
    """구현하면 status를 implemented로 바꾸게 한다."""
    planned = {c["table"] for c in CLASSES.values() if c["status"] == "planned"}
    assert not planned & set(TABLES)


def test_references_and_registries_exist():
    for name, cls in CLASSES.items():
        assert cls["status"] in ("implemented", "planned"), name
        assert sum(key in cls for key in ("table", "embedded_in", "source")) == 1, f"{name}: 저장 위치가 하나여야 한다"
        if cls["status"] == "implemented":
            assert "planned_stage" not in cls, name
        for field_name, field in cls["fields"].items():
            assert "references" not in field or "table" in CLASSES[field["references"]], f"{name}.{field_name}"
            assert "enum" not in field or field["enum"] in ONTOLOGY["enums"], f"{name}.{field_name}"
            assert "registry" not in field or field["registry"] in ONTOLOGY["registries"], f"{name}.{field_name}"
            assert "items" not in field or CLASSES[field["items"]].get("embedded_in", "").endswith("." + field_name)
            assert field["type"] != "enum" or "enum" in field, f"{name}.{field_name}"
    for registry in ONTOLOGY["registries"].values():
        assert (ROOT / registry["source"]).exists()


def test_enums_match_code_and_config():
    enums = ONTOLOGY["enums"]
    ledger = _config("ledger_app.yaml")
    assert enums["StaffRoleCode"] == list(security_db.ROLES)
    assert set(enums["AccessAction"]) == set(ACTION_LABELS)
    assert set(enums["ExamKind"]) == set(ledger["kinds"])
    assert set(enums["ProcedureType"]) == set(ledger["procedure_types"])
    assert set(enums["Sex"]) == set(ledger["sexes"].values())
    assert enums["ExamStage"] == list(STAGE_LABELS)


def test_workflow_matches_screen_stages_and_permissions():
    workflow = ONTOLOGY["workflow"]
    permissions = _config("security.yaml")["authentication"]["permissions"]
    assert workflow["labels"] == STAGE_LABELS
    assert [d["stage"] for d in workflow["derivation"]] == list(STAGE_LABELS)
    for transition in workflow["transitions"]:
        assert transition["permission"] in permissions, transition["action"]
        assert transition["guard"] in workflow["guards"], transition["action"]
        assert transition["to"] in STAGE_LABELS
        assert transition["from"] == "[*]" or transition["from"] in STAGE_LABELS
    # 종결을 제외한 모든 단계에서 나가는 전이가 있다(멈추는 단계가 없다).
    assert {t["from"] for t in workflow["transitions"]} >= set(STAGE_LABELS) - {"CLOSED"}
