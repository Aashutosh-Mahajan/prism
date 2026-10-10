"""Check scoring against real packet syntax and parent-side diff coordinates."""

from pathlib import Path

import pytest

from tests.benchmarks.packet_audit import composition
from tests.benchmarks.replay_precision import (
    git,
    historical_store,
    isolated_environment,
    parse_hunks,
    parse_packet,
    score_packet,
    select_commits,
    summarise,
)

PACKET = (
    "PRISM task · edit\n"
    "definition: prism/with spaces.py:3\n```\n3: LIMIT = 6\n```\n"
    "candidate: prism/prompt.py:10-13 (prompt) [excerpt]\n```\n"
    "10: def prompt():\n13:     return LIMIT\n```\n"
    "candidate: tests/test_prompt.py:1-2\n```\n1: def test_prompt():\n2:     assert prompt()\n```\n"
    "candidate: prism/omitted.py:4-6 [shown earlier in this session]\n"
    "Callers of prompt:\n  tests.test_prompt tests/test_prompt.py:2: assert prompt()\n"
    "Batch: independent files\nNext: run tests\n"
)


def test_packet_parser_includes_definitions_but_not_seen_blocks_or_callers() -> None:
    blocks = parse_packet(PACKET.replace("\n", "\r\n"))
    assert [(b.file, b.start, b.end) for b in blocks] == [
        ("prism/with spaces.py", 3, 3),
        ("prism/prompt.py", 10, 13),
        ("tests/test_prompt.py", 1, 2),
    ]
    assert blocks[1].source == "def prompt():\n    return LIMIT"
    assert blocks[1].delivered_lines == {10, 13}


def test_unterminated_fence_fails_instead_of_inflating_scores() -> None:
    with pytest.raises(ValueError, match="unterminated"):
        parse_packet("candidate: a.py:1-2\n```\n1: code")


@pytest.mark.parametrize(
    "role", ["implementation", "dependency", "similar", "construction candidate", "requested range"]
)
def test_every_source_role_counts(role: str) -> None:
    (block,) = parse_packet(f"{role}: prism/logic.py:1-2\n```\n1: first\n2: second\n```")
    assert block.file == "prism/logic.py" and block.delivered_lines == {1, 2}


def test_compact_numbering_and_omitted_lines() -> None:
    (block,) = parse_packet(
        "candidate: a.py:5-10\n```\n5: first\nsecond\n⋮ 3 lines omitted\n10: last\n```"
    )
    assert block.delivered_lines == {5, 6, 10}


def test_hunks_use_parent_coordinates_and_insertion_anchors() -> None:
    diff = (
        "--- a/prism/prompt.py\n+++ b/prism/prompt.py\n"
        "@@ -10,2 +10,3 @@\n@@ -13,0 +15 @@\n"
        "--- /dev/null\n+++ b/prism/new.py\n@@ -0,0 +1,5 @@\n"
        "--- a/prism/deleted.py\n+++ /dev/null\n@@ -1,3 +0,0 @@\n"
    )
    assert parse_hunks(diff) == [
        ("prism/prompt.py", 10, 11),
        ("prism/prompt.py", 13, 13),
        ("prism/deleted.py", 1, 3),
    ]


def test_score_does_not_claim_omitted_lines_and_counts_new_files_as_misses() -> None:
    row = score_packet(
        PACKET,
        ["prism/prompt.py", "prism/new.py"],
        [("prism/prompt.py", 10, 11), ("prism/prompt.py", 13, 13)],
    )
    assert row["found_files"] == 1 and row["expected_files"] == 2
    assert row["found_hunks"] == 1 and row["expected_hunks"] == 2
    assert 0 < row["useful_code_tokens"] < row["code_tokens"]
    summary = summarise([row])
    assert summary["file_recall_pct"] == 50 and summary["block_recall_pct"] == 50
    row["parent_missing_files"] = ["prism/new.py"]
    summary = summarise([row])
    assert summary["file_recall_pct"] == 50
    assert summary["existing_file_recall_pct"] == 100
    assert summary["new_file_targets"] == 1 and summary["all_new_commits"] == 0


def test_composition_categories_are_disjoint_and_prefixes_an_overlay() -> None:
    result = composition(PACKET)
    assert sum(result["characters_by_category"].values()) == len(PACKET)
    assert result["characters_by_category"]["test_code"] > 0
    assert result["test_caller_characters"] > 0
    assert result["line_prefix_characters"] == len("3: 10: 13: 1: 2: ")
    assert sum(result["share_pct"].values()) == pytest.approx(100)


def test_environment_is_restored_even_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    monkeypatch.setenv("PRISM_CONFIG_HOME", "original")
    monkeypatch.delenv("PRISM_SEMANTIC", raising=False)
    with pytest.raises(RuntimeError), isolated_environment(tmp_path):
        assert os.environ["PRISM_CONFIG_HOME"] != "original"
        assert os.environ["PRISM_SEMANTIC"] == "0"
        raise RuntimeError("fixture failure")
    assert os.environ["PRISM_CONFIG_HOME"] == "original"
    assert "PRISM_SEMANTIC" not in os.environ


def test_replay_indexes_parent_and_cleans_up_without_changing_checkout(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    (repo / "pyproject.toml").write_text("[project]\nname='fixture'\n", encoding="utf-8")
    (repo / "prism").mkdir()
    source = repo / "prism/rules.py"
    source.write_text("MIN_WORDS = 3\n", encoding="utf-8")
    git(repo, "add", ".")
    git(
        repo,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "-m",
        "feat: add the initial prompt word threshold",
    )
    parent = git(repo, "rev-parse", "HEAD")
    source.write_text("MIN_WORDS = 6\n", encoding="utf-8")
    git(repo, "add", ".")
    git(
        repo,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "-m",
        "fix: change the minimum prompt word threshold",
    )
    before = git(repo, "status", "--porcelain")
    (commit,) = select_commits(repo, 1, 10)
    assert commit["parent"] == parent and commit["gold"] == ["prism/rules.py"]
    assert select_commits(repo, 1, 10, parent) == []  # root commit has no parent
    base = tmp_path / "scratch"
    base.mkdir()
    with isolated_environment(base), historical_store(repo, base, parent) as store:
        assert (store.root / "prism/rules.py").read_text(encoding="utf-8") == "MIN_WORDS = 3\n"
        assert store.root != repo
    assert not (base / "source").exists()
    assert source.read_text(encoding="utf-8") == "MIN_WORDS = 6\n"
    assert git(repo, "status", "--porcelain") == before
    assert git(repo, "worktree", "list", "--porcelain").count("worktree ") == 1
