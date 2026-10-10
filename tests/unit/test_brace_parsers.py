"""Dart, Kotlin and Swift: declarations, line ranges, imports, calls and robustness."""

from __future__ import annotations

from pathlib import Path

import pytest

from prism.parsing.base_parser import get_parser

MOBILE = Path(__file__).parents[1] / "fixtures" / "repos" / "mobile"


def parse(language: str, rel: str, module: str):
    source = (MOBILE / rel).read_bytes()
    parser = get_parser(language)
    assert parser is not None
    return parser.parse(rel, source, module, False)


def by_qual(pf):
    return {s.qualname: s for s in pf.symbols}


def test_dart_classes_methods_and_ranges() -> None:
    pf = parse("dart", "lib/models/patient.dart", "lib.models.patient")
    assert pf.parse_error is None
    syms = by_qual(pf)
    assert syms["Patient"].kind == "class" and syms["Patient"].lines == (1, 22)
    assert syms["Patient.label"].kind == "method" and syms["Patient.label"].lines == (11, 14)
    assert syms["Patient.parse"].lines == (16, 21)
    assert syms["describe"].kind == "function" and syms["describe"].parent is None
    assert "Whether the patient is an adult" in syms["Patient.isAdult"].doc
    assert syms["Patient"].doc.startswith("A patient record")
    assert any(c.target == "Patient" for c in syms["Patient.parse"].calls)
    assert syms["Patient.parse"].complexity >= 2
    assert any(s.kind == "todo" for s in pf.smells)


def test_dart_imports_inheritance_and_privacy() -> None:
    pf = parse("dart", "lib/main.dart", "lib.main")
    mods = {r.module for r in pf.imports}
    assert "lib.models.patient" in mods and "lib.services.api" in mods
    assert not any("dart:" in m for m in mods)
    syms = by_qual(pf)
    assert set(syms["Home"].bases) >= {"Shape", "Mixin", "Comparable"}
    assert syms["Home._helper"].visibility == "private"
    assert syms["Home.load"].is_async
    assert any(c.target == "api.fetch" for c in syms["Home.load"].calls)
    assert syms["main"].kind == "function"


def test_kotlin_declarations_imports_and_visibility() -> None:
    rel = "android/app/src/main/kotlin/com/acme/Dose.kt"
    pf = parse("kotlin", rel, "main.kotlin.com.acme.Dose")
    assert pf.parse_error is None
    syms = by_qual(pf)
    assert {"Dose", "Dose.scaled", "Dose.secret", "Repo", "Repo.find", "main", "Registry"} <= set(
        syms
    )
    assert (
        syms["Dose.secret"].visibility == "private" and syms["Dose.scaled"].visibility == "public"
    )
    assert syms["Registry.load"].is_async
    assert "Closeable" in syms["Repo"].bases
    assert any(r.module == "com.acme.models" and r.name == "Patient" for r in pf.imports)
    assert any(c.target == "max" for c in syms["Dose.scaled"].calls)


def test_swift_types_extensions_and_initialisers() -> None:
    pf = parse("swift", "ios/Sources/Triage.swift", "ios.Sources.Triage")
    assert pf.parse_error is None
    syms = by_qual(pf)
    assert {
        "Triage",
        "Triage.init",
        "Triage.isUrgent",
        "Triage.helper",
        "Scorer",
        "Scorer.score",
        "run",
    } <= set(syms)
    assert syms["Triage.helper"].visibility == "private"
    assert set(syms["Triage"].bases) >= {"Codable", "Equatable"}
    assert syms["Triage.isUrgent"].complexity >= 2
    assert any(r.module == "Foundation" for r in pf.imports)
    assert any(c.target == "Triage.make" for c in syms["run"].calls)


@pytest.mark.parametrize("language", ["dart", "kotlin", "swift"])
def test_broken_and_hostile_input_never_raises(language: str) -> None:
    parser = get_parser(language)
    assert parser is not None
    for source in (
        b"",
        b"class {",
        b"}}}} {{{ '''",
        b"fun ( ) { \x00\xff",
        "é".encode("latin-1") * 50,
    ):
        pf = parser.parse("x", source, "x", False)
        assert pf.path == "x"
    assert parser.parse("x", b"class A {", "x", False).parse_error is not None
