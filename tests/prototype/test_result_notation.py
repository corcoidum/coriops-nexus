"""장부 결과 표기를 등록 코드로만 구조화하고 문장형 소견은 거부한다(A11)."""

import pytest
import yaml

from app.modules.endoscopy_pathology.result_notation import NotationError, ResultCodeBook


@pytest.fixture(scope="module")
def book():
    return ResultCodeBook.load()


@pytest.mark.parametrize(("notation", "expected"), [
    ("H#1", "H#1"),
    ("TA#2(L)", "TA#2(L)"),
    ("H#2, TA#2(L),CNI#2", "H#2, TA#2(L), CNI#2"),
    ("CG#2(im/e)", "CG#2(im/e)"),
    ("TA#4, inf.p#1", "TA#4, INF_P#1"),
    ("ADENOCARCINOMA", "ADENOCARCINOMA"),
])
def test_ledger_notation_round_trips(book, notation, expected):
    findings = book.parse_findings(notation)

    assert ", ".join(f.display() for f in findings) == expected
    assert all(f.registered for f in findings)


def test_unknown_code_or_modifier_is_kept_but_unregistered(book):
    unknown_code, unknown_mod = book.parse_findings("ZZ#1, TA#1(qq)")

    assert unknown_code.code == "ZZ" and not unknown_code.registered
    assert unknown_mod.modifiers == ("qq",) and not unknown_mod.registered


@pytest.mark.parametrize("notation", [
    "", " ", "TA#2(L),", "Tubular adenoma, low grade",
    "TA#0", "TA#2(L", "#2", "TA 2", "TA#2(L/e/im/x/y)", "결과#1",
])
def test_free_text_and_malformed_notation_is_rejected(book, notation):
    with pytest.raises(NotationError):
        book.parse_findings(notation)


def test_sydney_notation_round_trips(book):
    grades = book.parse_sydney("HP++/Neu++/Mon+++/Atr+/IM-")

    assert grades == {"h_pylori": "POS2", "neutrophil": "POS2", "mononuclear": "POS3",
                      "atrophy": "POS1", "intestinal_metaplasia": "NEG"}
    assert book.format_sydney(grades) == "HP++/Neu++/Mon+++/Atr+/IM-"
    assert book.parse_sydney("HP-/IM+") == {"h_pylori": "NEG", "intestinal_metaplasia": "POS1"}


@pytest.mark.parametrize("notation", ["HP", "HP++++", "XX+", "HP-/HP-", "HP-//IM-", "HP positive"])
def test_malformed_sydney_is_rejected(book, notation):
    with pytest.raises(NotationError):
        book.parse_sydney(notation)


def test_code_book_matches_the_ontology_contract():
    """config 등록값이 ontology enum·필드와 어긋나지 않는다."""
    with open("ontology/coriops.yaml", encoding="utf-8") as source:
        ontology = yaml.safe_load(source)
    with open("config/result_codes.yaml", encoding="utf-8") as source:
        codes = yaml.safe_load(source)

    assert set(codes["sydney_grades"].values()) == set(ontology["enums"]["SydneyGrade"])
    assert set(codes["sydney_notation"].values()) <= set(ontology["classes"]["SydneyGrading"]["fields"])
    for meta in codes["codes"].values():
        assert meta["severity_tier"] in (None, *ontology["enums"]["ResultSeverityTier"])
        assert meta["scope"] in (None, *ontology["enums"]["ResultCodeScope"])
