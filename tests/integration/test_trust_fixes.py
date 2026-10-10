"""Regression tests for retrieval trust: what Prism claims is complete, new, or delivered must be true.

Each test pins a defect found by the local reliability matrix (Unicode text, encodings, line
numbering, size-skipped files, changed numbers, Java calls, caches in unenabled repos, and
delivery of source to a client that never read the reply).
"""

from __future__ import annotations

import json
import unicodedata
from pathlib import Path

import pytest

from prism.consent import registry_path
from prism.lifecycle import apply_init, plan_init, scan
from prism.navigator import api as nav
from prism.navigator.store import IndexStore


def make_repo(root: Path, files: dict[str, bytes | str]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
    apply_init(plan_init(root))
    scan(root)
    return root


def task(root: Path, query: str, **kwargs: object) -> dict:
    store = IndexStore.open(root)
    try:
        return nav.op_task(store, query, 2000, None, "auto", None, **kwargs)  # type: ignore[arg-type]
    finally:
        store.close()


def literal_lines(pack: dict, contains: str) -> set[tuple[str, int]]:
    return {
        (o["file"], o["line"])
        for lit in pack.get("literals", [])
        if contains in lit["text"]
        for o in lit["occurrences"]
    }


@pytest.mark.parametrize(
    "text",
    ["Ошибка оплаты", "支付失败", "שלום עולם", "Zahlung für Bestellung"],
)
def test_non_ascii_strings_are_found_exhaustively(tmp_path: Path, text: str) -> None:
    repo = make_repo(
        tmp_path / "r",
        {
            "a.py": f'def a():\n    return "{text}"\n',
            "b.py": f'def b():\n    return "{text}"\n',
        },
    )
    pack = task(repo, f'change the message "{text}"')
    assert literal_lines(pack, text) == {("a.py", 2), ("b.py", 2)}


def test_decomposed_text_matches_composed_and_keeps_the_users_spelling(tmp_path: Path) -> None:
    nfd = unicodedata.normalize("NFD", "café fermé")
    repo = make_repo(tmp_path / "r", {"a.py": f'def a():\n    return "{nfd}"\n'})
    pack = task(repo, 'edit the text "café fermé"')
    assert literal_lines(pack, "caf") == {("a.py", 2)}
    pack = task(repo, f'edit the text "{nfd}"')
    assert any(lit["text"] == nfd for lit in pack["literals"])  # echoed as typed


def test_non_ascii_identifier_is_not_truncated(tmp_path: Path) -> None:
    repo = make_repo(
        tmp_path / "r",
        {"m.py": "def greet_café():\n    return 1\n\n\ndef x():\n    return greet_café()\n"},
    )
    pack = task(repo, "fix greet_café")
    assert not pack.get("absent")
    assert literal_lines(pack, "greet_café")


def test_name_inside_a_longer_word_is_not_declared_new(tmp_path: Path) -> None:
    repo = make_repo(
        tmp_path / "r", {"m.py": 'def f():\n    return "' + "x" * 700 + 'MARK_LONGLINE_TAIL"\n'}
    )
    pack = task(repo, "MARK_LONGLINE_TAIL")
    assert "MARK_LONGLINE_TAIL" not in (pack.get("absent") or [])
    assert literal_lines(pack, "MARK_LONGLINE_TAIL") == {("m.py", 2)}


def test_a_really_new_name_is_still_reported_new(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "r", {"m.py": "def f():\n    return 1\n"})
    pack = task(repo, "add brand_new_helper_name to f")
    assert "brand_new_helper_name" in (pack.get("absent") or [])


def test_a_name_only_in_a_size_skipped_file_is_not_called_new(tmp_path: Path) -> None:
    root = tmp_path / "r"
    root.mkdir()
    (root / "prism.toml").write_text("max_file_size = 200\n", encoding="utf-8")
    big = "# padding " + "x" * 400 + "\n\ndef over_limit_mark():\n    return 1\n"
    repo = make_repo(root, {"small.py": "def s():\n    return 1\n", "big.py": big})
    pack = task(repo, "rename over_limit_mark")
    assert "over_limit_mark" not in (pack.get("absent") or [])


def test_latin1_and_lone_cr_python_sources_are_delivered_exactly(tmp_path: Path) -> None:
    latin = (
        '# -*- coding: latin-1 -*-\n\n\ndef latin_func():\n    return "MARK_LATIN_café"\n'
    ).encode("latin-1")
    lone_cr = "\r".join(["", "", "def cr_func():", '    return "MARK_LONECR_VALUE"', ""]).encode()
    repo = make_repo(tmp_path / "r", {"latin.py": latin, "cr.py": lone_cr})
    assert literal_lines(task(repo, 'find "MARK_LATIN_café"'), "MARK_LATIN") == {("latin.py", 5)}
    pack = task(repo, "MARK_LONECR_VALUE")
    assert literal_lines(pack, "MARK_LONECR_VALUE") == {
        ("cr.py", 4)
    }  # Python counts a lone CR as a newline


def test_file_with_stray_invalid_utf8_still_gets_its_symbols(tmp_path: Path) -> None:
    raw = b'def inv_func():\n    return "ok"\n# bad byte: \xff\xfe\n'
    repo = make_repo(tmp_path / "r", {"inv.py": raw})
    store = IndexStore.open(repo)
    try:
        assert store.symbol("inv.inv_func") is not None
    finally:
        store.close()


def test_changed_number_lists_every_site_including_other_languages(tmp_path: Path) -> None:
    repo = make_repo(
        tmp_path / "r",
        {
            "backend/rules.py": "def check(age):\n    if age < 23:\n        raise ValueError('at least 23 years old')\n",
            "backend/exp.py": "def max_experience(age):\n    return age - 23  # min age for practice\n",
            "web/page.tsx": "export const maxDob = () => new Date().getFullYear() - 23; // age limit\n",
            "backend/ports.py": "PORT = 8023\nTIMEOUT = 23\n",
        },
    )
    pack = task(
        repo, "The minimum age for registration is changing from 23 to 25. Update every place."
    )
    lines = literal_lines(pack, "23")
    assert {"backend/rules.py", "backend/exp.py", "web/page.tsx"} <= {f for f, _ in lines}
    assert "backend/ports.py" not in {f for f, _ in lines}  # off-topic number: noise


def test_java_unqualified_and_this_calls_resolve_to_the_enclosing_class(tmp_path: Path) -> None:
    pytest.importorskip("tree_sitter")
    java = (
        "package shop;\npublic class Discounts {\n"
        "    double apply(double a, int pct) { return a - a * pct / 100; }\n"
        "    double cartTotal(double[] items) {\n        double sum = 0;\n"
        "        return apply(sum, 10);\n    }\n"
        "    double viaThis(double a) { return this.apply(a, 5); }\n}\n"
    )
    repo = make_repo(tmp_path / "r", {"shop/Discounts.java": java})
    data = json.loads((repo / ".aicontext" / "symbols.json").read_text(encoding="utf-8"))
    by_name = {s["id"].rsplit(".", 1)[-1]: s for s in data["symbols"]}
    assert any(c.endswith("apply") for c in by_name["cartTotal"]["calls"])
    assert any(c.endswith("apply") for c in by_name["viaThis"]["calls"])


def test_syntax_error_in_a_tree_sitter_language_is_reported(tmp_path: Path) -> None:
    pytest.importorskip("tree_sitter")
    repo = make_repo(
        tmp_path / "r",
        {"ok.js": "function good(){ return 1 }\n", "bad.js": "function broken( { return 1\n"},
    )
    manifest = json.loads((repo / ".aicontext" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["files"]["bad.js"].get("parse_error")
    assert not manifest["files"]["ok.js"].get("parse_error")


def test_a_repo_the_user_never_enabled_is_never_written_to(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "r", {"m.py": "def f():\n    return 1\n"})
    registry_path().unlink()  # a teammate's committed index; not enabled for this user
    before = {p: p.read_bytes() for p in repo.rglob("*") if p.is_file()}
    task(repo, "where is f")
    task(repo, "where is f used")
    after = {p: p.read_bytes() for p in repo.rglob("*") if p.is_file()}
    assert before == after  # caches, activity log and sessions went to the user's own cache dir


def test_unconsumed_reply_is_not_treated_as_delivered(tmp_path: Path) -> None:
    from prism.mcp.server import PrismTools

    repo = make_repo(
        tmp_path / "r",
        {"m.py": "def calc_total(x):\n    return x * 2\n\n\ndef other():\n    return 1\n"},
    )
    tools = PrismTools(repo)
    first = tools.prism_task("calc_total")
    retry = tools.prism_task(
        "calc_total"
    )  # identical request: the first reply may never have arrived
    assert any("source" in b for b in first["blocks"])
    assert any("source" in b for b in retry["blocks"])
    followup = tools.prism_task("where is calc_total used")  # a different request proves delivery
    again = tools.prism_task("calc_total in m.py")
    assert any(b.get("seen") for b in again["blocks"]) or any(
        "source" in b for b in followup["blocks"]
    )


def test_mcp_stops_serving_the_moment_consent_is_revoked(tmp_path: Path) -> None:
    from prism.mcp.server import PrismTools

    repo = make_repo(tmp_path / "r", {"m.py": "def f():\n    return 1\n"})
    tools = PrismTools(repo)
    assert "blocks" in tools.prism_task("f")
    registry_path().unlink()
    reply = tools.prism_task("f")
    assert reply.get("error") == "not_enabled"


def test_incremental_update_equals_a_fresh_scan_for_small_repos(tmp_path: Path) -> None:
    from prism.lifecycle import update

    repo = make_repo(
        tmp_path / "r",
        {"a.py": "def a():\n    return b()\n", "b.py": "def b():\n    return 1\n"},
    )
    (repo / "c.py").write_text("def c():\n    return a()\n", encoding="utf-8")
    update(repo, files=["c.py"])
    incremental = (repo / ".aicontext" / "symbols.json").read_bytes()
    scan(repo, full=True)
    assert (repo / ".aicontext" / "symbols.json").read_bytes() == incremental


def _verify(repo: Path, request: str) -> dict:
    store = IndexStore.open(repo)
    try:
        return nav.op_task(store, request, 2000, None, "verify", None)
    finally:
        store.close()


def _sites(pack: dict) -> set[str]:
    return {o["file"] for lit in pack.get("literals", []) for o in lit["occurrences"]}


def test_verify_mode_lists_only_the_sites_that_still_match_after_an_edit(tmp_path: Path) -> None:
    repo = make_repo(
        tmp_path / "r",
        {
            "a.py": "def check(age):\n    return age >= 23  # minimum age\n",
            "b.py": "def limit(age):\n    return age - 23  # years of age\n",
        },
    )
    request = "The minimum age is changing from 23 to 25."
    before = _verify(repo, request)
    assert before["intent"] == "verify" and before["blocks"] == []
    assert _sites(before) == {"a.py", "b.py"}
    (repo / "a.py").write_text(
        "def check(age):\n    return age >= 25  # minimum age\n", encoding="utf-8"
    )
    assert _sites(_verify(repo, request)) == {"b.py"}
    (repo / "b.py").write_text(
        "def limit(age):\n    return age - 25  # years of age\n", encoding="utf-8"
    )
    done = _verify(repo, request)
    assert not done.get("literals") and "No remaining matches" in done["next"]


def test_old_value_search_covers_translations_and_config_not_just_code(tmp_path: Path) -> None:
    repo = make_repo(
        tmp_path / "r",
        {
            "app/rules.py": "def check(age):\n    return age >= 23  # minimum age for doctors\n",
            "locales/hi.json": '{"Doctors must be at least 23 years old": "डॉक्टरों की उम्र कम से कम 23 वर्ष"}\n',
            "locales/bn.json": '{"Doctors must be at least 23 years old": "ডাক্তারদের বয়স কমপক্ষে 23"}\n',
            "docs/notes.md": "The minimum age for doctors is 23.\n",
            "config/ports.yaml": "port: 8023\ntimeout: 23\n",
        },
    )
    pack = task(repo, "The minimum age for doctors is changing from 23 to 25. Update every place.")
    files = {f for f, _ in literal_lines(pack, "23")}
    assert {"app/rules.py", "locales/hi.json", "locales/bn.json", "docs/notes.md"} <= files
    assert "config/ports.yaml" not in files  # a 23 that has nothing to do with the request
    # data files hold literals; they never become code blocks
    assert all(b["file"].endswith(".py") for b in pack["blocks"])


def test_text_corpus_follows_edits_and_new_files(tmp_path: Path) -> None:
    repo = make_repo(
        tmp_path / "r",
        {
            "app/rules.py": "def check(age):\n    return age >= 23  # minimum age\n",
            "locales/hi.json": '{"min age 23": "x"}\n',
        },
    )
    request = "The minimum age is changing from 23 to 25."
    assert ("locales/hi.json", 1) in literal_lines(task(repo, request), "23")
    (repo / "locales" / "hi.json").write_text('{"min age 25": "x"}\n', encoding="utf-8")
    (repo / "locales" / "ta.json").write_text('{"min age 23": "y"}\n', encoding="utf-8")
    sites = literal_lines(task(repo, request + " now"), "23")
    assert ("locales/hi.json", 1) not in sites
    assert ("locales/ta.json", 1) in sites


def test_a_condition_is_not_mistaken_for_an_old_value(tmp_path: Path) -> None:
    repo = make_repo(
        tmp_path / "r",
        {
            "a.py": "def pct(x):\n    rate = 100  # the rate\n    return round(x * (rate - 5) / 100, 2)\n"
        },
    )
    pack = task(repo, "Ignore any coupon above 100 percent when computing the price")
    assert not [lit for lit in pack.get("literals", []) if lit["kind"] == "number"]
    pack = task(repo, "The rate is changing from 100 to 90 everywhere")
    assert [lit for lit in pack.get("literals", []) if lit["kind"] == "number"]


def test_damaged_cache_databases_are_dropped_and_rebuilt(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from prism.cli import app

    repo = make_repo(tmp_path / "r", {"m.py": "def calc_total(x):\n    return x * 2\n"})
    runner = CliRunner()
    assert runner.invoke(app, ["task", "calc_total", "--root", str(repo), "--json"]).exit_code == 0
    for db in (repo / ".aicontext" / "cache").glob("*.sqlite"):
        db.write_bytes(db.read_bytes()[: max(10, db.stat().st_size // 3)])
    again = runner.invoke(app, ["task", "calc_total again", "--root", str(repo), "--json"])
    assert again.exit_code == 0
    assert json.loads(again.output)["blocks"]
    assert runner.invoke(app, ["scan", "--root", str(repo)]).exit_code == 0


def test_links_leading_outside_the_repo_are_never_indexed(tmp_path: Path) -> None:
    import os
    import subprocess

    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "leak.py").write_text(
        "LEAK = 1\n\n\ndef outside_leak_fn():\n    return LEAK\n", encoding="utf-8"
    )
    root = tmp_path / "r"
    root.mkdir()
    (root / "m.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    link = root / "linked"
    try:
        os.symlink(outside, link, target_is_directory=True)
    except OSError:  # no symlink privilege on this Windows account: use a junction
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(outside)], check=True, capture_output=True
        )
    apply_init(plan_init(root))
    scan(root)
    manifest = json.loads((root / ".aicontext" / "manifest.json").read_text(encoding="utf-8"))
    assert "linked/leak.py" not in manifest["files"]
    assert not any("leak" in f for f in manifest["files"])


def test_usage_errors_and_declined_prompts_exit_with_user_error_codes(tmp_path: Path) -> None:
    import subprocess
    import sys

    def run(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-X", "utf8", "-m", "prism", *args],
            capture_output=True,
            text=True,
            input="",
            cwd=tmp_path,
            timeout=120,
        )

    assert run("task", "--no-such-option").returncode == 1
    assert run("no-such-command").returncode == 1
    assert run("--root", str(tmp_path / "missing"), "status").returncode == 1


def test_uninstall_removes_the_directories_it_emptied(tmp_path: Path) -> None:
    from prism.integrations.base import _prune_empty_parents

    root = tmp_path / "r"
    deep = root / ".claude" / "skills" / "prism-audit"
    deep.mkdir(parents=True)
    _prune_empty_parents(root, deep)
    assert not (root / ".claude").exists() and root.exists()
    kept = root / ".claude" / "skills" / "mine"
    kept.mkdir(parents=True)
    (kept / "SKILL.md").write_text("x", encoding="utf-8")
    other = root / ".claude" / "skills" / "prism-audit"
    other.mkdir()
    _prune_empty_parents(root, other)
    assert (kept / "SKILL.md").exists() and not other.exists()
