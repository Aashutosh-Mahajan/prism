"""Twins, ready patches, read ranges, scope and the brief detail level."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from prism.lifecycle import apply_init, plan_init, scan
from prism.navigator import enrich
from prism.navigator.api import op_task
from prism.navigator.store import IndexStore
from prism.navigator.task_pack import render_task


def write(root: Path, rel: str, text: str | bytes) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text if isinstance(text, bytes) else text.encode("utf-8"))


def index(root: Path) -> None:
    apply_init(plan_init(root))
    scan(root)


def task(root: Path, query: str, budget: int = 2000, detail: str = "full") -> dict:
    store = IndexStore.open(root)
    try:
        return op_task(store, query, budget, detail=detail)
    finally:
        store.close()


# --- scope ---------------------------------------------------------------------------------


def test_archived_code_and_other_areas_rank_lower() -> None:
    assert enrich.scope_factor("fix the validation", "archive/old/validators.py") < 1.0
    assert enrich.scope_factor("fix the archive loader", "archive/loader.py") == 1.0
    assert enrich.scope_factor("update the backend validation", "frontend/app/page.tsx") < 1.0
    assert enrich.scope_factor("update the backend validation", "backend/api/views.py") == 1.0
    # naming both areas, or none, ranks neither down
    assert enrich.scope_factor("change backend and frontend", "frontend/app/page.tsx") == 1.0
    assert enrich.scope_factor("fix the validation", "frontend/app/page.tsx") == 1.0


# --- twins ---------------------------------------------------------------------------------

CERT = (
    "def validate_medical_certificate(file):\n"
    '    """Validate a certificate upload."""\n'
    "    allowed = ['pdf', 'jpg', 'png']\n"
    "    ext = file.name.split('.')[-1].lower()\n"
    "    if ext not in allowed:\n"
    "        raise ValueError('bad type')\n"
    "    if file.size > 10 * 1024 * 1024:\n"
    "        raise ValueError('too big')\n"
)


def test_the_same_function_in_two_files_is_named_as_a_twin(tmp_path: Path) -> None:
    write(tmp_path, "pyproject.toml", "[project]\nname='x'\n")
    write(tmp_path, "backend/accounts/validators.py", CERT)
    write(tmp_path, "backend/patients/validators.py", CERT.replace("'pdf', ", "'pdf', 'gif', "))
    index(tmp_path)
    pack = task(tmp_path, "Allow WEBP in validate_medical_certificate")
    (twin,) = pack["twins"]
    assert twin["name"] == "validate_medical_certificate" and len(twin["copies"]) == 1
    text = render_task(pack)
    assert "Twins: validate_medical_certificate is defined in 2 files" in text
    assert "backend/patients/validators.py" in text and "backend/accounts/validators.py" in text


def test_generic_names_are_not_twins(tmp_path: Path) -> None:
    write(tmp_path, "pyproject.toml", "[project]\nname='x'\n")
    body = "def get(self):\n    return self.items\n"
    for name in ("a", "b", "c"):
        write(tmp_path, f"pkg/{name}.py", body)
    index(tmp_path)
    assert "twins" not in task(tmp_path, "change get to return a copy")


def test_unrelated_functions_with_a_shared_name_are_not_twins(tmp_path: Path) -> None:
    write(tmp_path, "pyproject.toml", "[project]\nname='x'\n")
    write(
        tmp_path,
        "a/report.py",
        "def build_report_rows(items):\n    return [str(i) for i in items]\n",
    )
    write(
        tmp_path,
        "b/report.py",
        "def build_report_rows(config, db, user):\n    rows = db.query(user)\n    for r in rows:\n        config.log(r)\n    return rows\n",
    )
    index(tmp_path)
    assert "twins" not in task(tmp_path, "fix build_report_rows")


# --- patch ---------------------------------------------------------------------------------


def make_age_repo(root: Path) -> None:
    write(root, "pyproject.toml", "[project]\nname='x'\n")
    write(
        root,
        "backend/rules.py",
        "# minimum doctor age\n\nMIN_DOCTOR_AGE = 23\n\n\ndef check(age):\n    if age < 23:\n        raise ValueError('Doctor must be at least 23 years old')\n    return age - 23\n",
    )
    # Windows line endings and no newline at the end of the file must both survive.
    write(
        root,
        "backend/crlf.py",
        b"# doctor age rule\r\nLIMIT = 23  # minimum doctor age\r\nNAME = 'x'\r\n",
    )
    write(root, "docs/rule.md", "The minimum doctor age is 23")
    index(root)


REQUEST = "The minimum doctor age is changing from 23 to 25. Update the code and messages."


def test_a_mechanical_change_gets_a_checked_patch_that_applies_exactly(tmp_path: Path) -> None:
    make_age_repo(tmp_path)
    pack = task(tmp_path, REQUEST)
    patch = pack["patch"]
    assert patch["old"] == "23" and patch["new"] == "25" and patch["sites"] >= 5
    assert enrich.APPLY_COMMAND in render_task(pack) and patch["path"] in render_task(pack)
    patch_file = tmp_path / patch["path"]
    assert patch_file.is_file()

    before = {
        p: (tmp_path / p).read_bytes()
        for p in ("backend/rules.py", "backend/crlf.py", "docs/rule.md")
    }
    done = subprocess.run(
        ["git", "-c", "core.autocrlf=false", "apply", str(patch_file)],
        cwd=tmp_path,
        capture_output=True,
    )
    assert done.returncode == 0, done.stderr
    after = {p: (tmp_path / p).read_bytes() for p in before}
    for name, old in before.items():
        assert after[name] == old.replace(b"23", b"25"), name  # only the value changed
    assert after["backend/crlf.py"].count(b"\r\n") == 3  # line endings kept
    assert not after["docs/rule.md"].endswith(b"\n")  # still no newline at the end


def test_no_patch_without_an_explicit_old_and_new_value(tmp_path: Path) -> None:
    make_age_repo(tmp_path)
    pack = task(tmp_path, "The minimum doctor age 23 should be raised. Update the code.")
    assert "patch" not in pack


def test_no_patch_when_the_literal_list_is_not_exhaustive(tmp_path: Path) -> None:
    write(tmp_path, "pyproject.toml", "[project]\nname='x'\n")
    for i in range(60):
        write(tmp_path, f"pkg/m{i}.py", f"LIMIT_{i} = 23  # doctor age limit\n")
    index(tmp_path)
    assert "patch" not in task(tmp_path, REQUEST)


def test_a_rename_gets_a_patch_only_when_the_new_name_is_free(tmp_path: Path) -> None:
    write(tmp_path, "pyproject.toml", "[project]\nname='x'\n")
    write(tmp_path, "pkg/a.py", "def verify_email(x):\n    return x\n")
    write(tmp_path, "pkg/b.py", "from pkg.a import verify_email\n\nprint(verify_email(1))\n")
    index(tmp_path)
    pack = task(tmp_path, "Rename verify_email to confirm_email everywhere")
    assert pack["patch"]["old"] == "verify_email" and pack["patch"]["new"] == "confirm_email"
    subprocess.run(
        ["git", "-c", "core.autocrlf=false", "apply", str(tmp_path / pack["patch"]["path"])],
        cwd=tmp_path,
        check=True,
    )
    assert "verify_email" not in (tmp_path / "pkg/b.py").read_text()
    assert "confirm_email" in (tmp_path / "pkg/a.py").read_text()

    # the new name already exists: a blind rename could merge two things
    write(tmp_path, "pkg/c.py", "def confirm_email(x):\n    return x\n")
    write(tmp_path, "pkg/d.py", "def verify_mail(x):\n    return x\n")
    index(tmp_path)
    assert "patch" not in task(tmp_path, "Rename confirm_email to verify_mail everywhere")


def test_a_patch_is_rebuilt_when_its_file_was_pruned(tmp_path: Path) -> None:
    make_age_repo(tmp_path)
    first = task(tmp_path, REQUEST)["patch"]["path"]
    (tmp_path / first).unlink()
    second = task(tmp_path, REQUEST)["patch"]["path"]
    assert (tmp_path / second).is_file()


def test_replacements_are_parsed_from_the_usual_phrasings() -> None:
    parse = enrich.parse_replacements
    assert [(r.old, r.new) for r in parse("changing from 23 to 25.")] == [("23", "25")]
    assert [(r.old, r.new) for r in parse("stay valid for 15 minutes instead of 10")] == [
        ("10", "15")
    ]
    assert [(r.old, r.new) for r in parse("raise it 10 -> 20")] == [("10", "20")]
    assert [(r.old, r.new, r.kind) for r in parse("rename getUser to fetchUser")] == [
        ("getUser", "fetchUser", "identifier")
    ]
    assert parse("make it faster") == []
    assert parse("from 5 to 5") == []


def test_numeric_patch_does_not_replace_a_decimal_prefix(tmp_path: Path) -> None:
    write(tmp_path, "pyproject.toml", "[project]\nname='x'\n")
    write(tmp_path, "rules.py", "MIN_DOCTOR_AGE = 23; RATIO = 23.5  # doctor age\n")
    index(tmp_path)
    pack = task(tmp_path, REQUEST)
    subprocess.run(
        ["git", "-c", "core.autocrlf=false", "apply", str(tmp_path / pack["patch"]["path"])],
        cwd=tmp_path,
        check=True,
    )
    assert (
        tmp_path / "rules.py"
    ).read_text() == "MIN_DOCTOR_AGE = 25; RATIO = 23.5  # doctor age\n"


def test_scattered_read_windows_never_become_a_whole_file() -> None:
    class Reader:
        def lines(self, path: str) -> list[str]:
            return ["row"] * 2000

    ranges = enrich.read_ranges(Reader(), {"large.json": list(range(1, 2001, 50))})
    assert ranges and all(window["limit"] <= 120 for window in ranges)


def test_multiple_numeric_replacements_do_not_cascade(tmp_path: Path) -> None:
    write(tmp_path, "pyproject.toml", "[project]\nname='x'\n")
    write(tmp_path, "rules.py", "DOCTOR_MIN_AGE = 10; DOCTOR_MAX_AGE = 20  # doctor age\n")
    index(tmp_path)
    pack = task(tmp_path, "The doctor age limits change from 10 to 20 and from 20 to 30.")
    subprocess.run(
        ["git", "-c", "core.autocrlf=false", "apply", str(tmp_path / pack["patch"]["path"])],
        cwd=tmp_path,
        check=True,
    )
    assert (tmp_path / "rules.py").read_text() == (
        "DOCTOR_MIN_AGE = 20; DOCTOR_MAX_AGE = 30  # doctor age\n"
    )


def test_conflicting_replacement_destinations_offer_no_patch(tmp_path: Path) -> None:
    make_age_repo(tmp_path)
    pack = task(tmp_path, "The doctor age changes from 23 to 25 and from 23 to 26.")
    assert "patch" not in pack


def test_no_tests_is_reported_instead_of_implying_a_clean_finish(tmp_path: Path) -> None:
    write(tmp_path, "pyproject.toml", "[tool.pytest.ini_options]\n")
    write(tmp_path, "rules.py", "def apply_surcharge_rule(amount):\n    return amount * 1.2\n")
    index(tmp_path)
    pack = task(tmp_path, "change apply_surcharge_rule to add 5 percent")
    assert "No indexed tests found" in render_task(pack)


# --- read ranges, brief, tests -------------------------------------------------------------


def test_large_files_get_read_windows_around_the_sites(tmp_path: Path) -> None:
    write(tmp_path, "pyproject.toml", "[project]\nname='x'\n")
    rows = [f'    "key{i}": "value {i}",' for i in range(800)]
    rows[400] = '    "doctor limit": "age 23 years",'
    write(tmp_path, "data/messages.py", "MESSAGES = {\n" + "\n".join(rows) + "\n}\n")
    write(tmp_path, "pkg/mod.py", "AGE = 23  # doctor age\n")
    index(tmp_path)
    pack = task(tmp_path, "The doctor age is changing from 23 to 25", detail="full")
    ranges = pack.get("read_ranges", [])
    if ranges:  # a patch makes windows unnecessary; either way the windows must be small
        assert all(r["limit"] <= 120 and r["total"] >= 600 for r in ranges)


def test_brief_is_smaller_and_keeps_the_sites(tmp_path: Path) -> None:
    make_age_repo(tmp_path)
    full = task(tmp_path, REQUEST, budget=2000)
    brief = task(tmp_path, REQUEST, budget=2000, detail="brief")
    assert brief["budget"]["used_est"] <= 800 < full["budget"]["requested"]
    assert (brief["literals"] and "links" not in brief) or all(
        link["role"] == "test" for link in brief.get("links", [])
    )
    with pytest.raises(Exception, match="full or brief"):
        task(tmp_path, REQUEST, detail="huge")


def test_nearest_tests_are_offered_when_nothing_links(tmp_path: Path) -> None:
    write(tmp_path, "pyproject.toml", "[tool.pytest.ini_options]\n")
    write(
        tmp_path,
        "pkg/pricing_rules.py",
        "def apply_surcharge_rule(amount):\n    return amount * 1.2\n",
    )
    write(tmp_path, "tests/test_pricing_rules.py", "def test_placeholder():\n    assert True\n")
    index(tmp_path)
    pack = task(tmp_path, "change apply_surcharge_rule to add 5 percent")
    assert any(link["file"] == "tests/test_pricing_rules.py" for link in pack.get("links", []))


def test_unmapped_tests_in_an_unrelated_directory_are_not_lost(tmp_path: Path) -> None:
    write(tmp_path, "pyproject.toml", "[tool.pytest.ini_options]\n")
    write(tmp_path, "pkg/rules.py", "def apply_surcharge_rule(amount):\n    return amount * 1.2\n")
    write(tmp_path, "tests/test_checkout.py", "def test_placeholder():\n    assert True\n")
    index(tmp_path)
    pack = task(tmp_path, "change apply_surcharge_rule to add 5 percent")
    assert "tests/test_checkout.py" in pack["run"]


def test_indirect_tests_follow_call_graph_distance(tmp_path: Path) -> None:
    from prism.navigator.source_index import SourceIndex
    from prism.navigator.task_pack import _related_tests

    write(tmp_path, "pyproject.toml", "[tool.pytest.ini_options]\n")
    write(tmp_path, "rules.py", "def surcharge(amount):\n    return amount * 1.2\n")
    write(
        tmp_path,
        "checkout.py",
        "from rules import surcharge\n\ndef total(amount):\n    return surcharge(amount)\n",
    )
    write(
        tmp_path,
        "tests/test_checkout.py",
        "from checkout import total\n\ndef test_total():\n    assert total(10) == 12\n",
    )
    write(
        tmp_path,
        "tests/test_rules.py",
        "from rules import surcharge\n\ndef test_surcharge():\n    assert surcharge(10) == 12\n",
    )
    index(tmp_path)
    store = IndexStore.open(tmp_path)
    try:
        symbol = store.symbols_named("surcharge")[0]
        with SourceIndex(store) as source:
            selected = _related_tests(store, source, symbol)
        assert selected[:2] == ["tests/test_rules.py", "tests/test_checkout.py"]
    finally:
        store.close()
