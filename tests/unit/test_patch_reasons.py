from pathlib import Path
from types import SimpleNamespace

import pytest

from prism.navigator import enrich
from prism.navigator.literals import EvidenceResult, Occurrence


@pytest.mark.parametrize(
    "reason",
    [
        "no_replacement",
        "conflicting_destinations",
        "not_exhaustive",
        "new_name_exists",
        "new_name_unverified",
        "line_changed",
        "git_rejected",
        "cache_unavailable",
        "generic_name",
    ],
)
def test_patch_refusals_have_specific_reasons(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reason: str
) -> None:
    source = tmp_path / "rules.py"
    source.write_text("OLD_LIMIT = 23\n", encoding="utf-8")
    replacement = enrich.Replacement("OLD_LIMIT", "NEW_LIMIT", "identifier")
    # Supply exactly the indexed evidence so the refusal itself is isolated.
    evidence = EvidenceResult()
    evidence.absent = ["NEW_LIMIT"]
    evidence.literals = [
        SimpleNamespace(
            kind="identifier",
            text="OLD_LIMIT",
            complete=True,
            occurrences=[Occurrence("rules.py", 1, "OLD_LIMIT = 23", 0)],
        )
    ]
    reader = SimpleNamespace(lines=lambda file: ["OLD_LIMIT = 23"])
    replacements = [replacement]
    if reason == "no_replacement":
        replacements = []
    elif reason == "generic_name":
        replacements = [enrich.Replacement("id", "object_id", "identifier")]
    elif reason == "conflicting_destinations":
        replacements.append(enrich.Replacement("OLD_LIMIT", "OTHER_LIMIT", "identifier"))
    elif reason == "not_exhaustive":
        evidence.literals[0].complete = False
    elif reason == "new_name_exists":
        evidence.absent = []
        evidence.literals.append(
            SimpleNamespace(
                kind="identifier",
                text="NEW_LIMIT",
                complete=True,
                occurrences=[Occurrence("rules.py", 2, "NEW_LIMIT = 1", 0)],
            )
        )
    elif reason == "new_name_unverified":
        evidence.absent = []  # could not be proven new within the time allowed
    elif reason == "line_changed":
        reader.lines = lambda file: ["OLD_LIMIT = 25"]
    elif reason == "cache_unavailable":
        blocked = tmp_path / "blocked"
        blocked.write_text("file", encoding="utf-8")
        monkeypatch.setattr("prism.consent.cache_root", lambda root: blocked)
    else:
        monkeypatch.setattr(enrich, "_git_accepts", lambda *args: False)
    monkeypatch.setattr(enrich, "parse_replacements", lambda query: replacements)
    assert enrich.build_patch(SimpleNamespace(root=tmp_path), reader, "request", evidence) == reason
