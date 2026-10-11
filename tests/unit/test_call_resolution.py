import json
from pathlib import Path

import pytest

from prism.consent import RepoEntry, get_entry, set_entry
from prism.core.errors import NotEnabledError
from prism.graph import build_call_graph
from prism.lifecycle import apply_init, plan_init, scan
from prism.maintenance import migrate
from prism.navigator.store import IndexStore
from tests.unit.test_graph import make_table


def test_scope_and_type_resolution_are_distinct_from_unique_name() -> None:
    table = make_table(
        {
            "a.py": """
        class Base:
            def inherited(self): pass
        class Child(Base):
            def run(self): self.inherited()
        def use(obj): obj.inherited()
    """
        }
    )
    graph = build_call_graph(table)
    edges = {edge.source: edge for edge in graph.edges}
    assert edges["a.Child.run"].confidence == "medium"
    assert edges["a.Child.run"].resolution == "resolved"
    assert edges["a.use"].confidence == "low"
    assert edges["a.use"].resolution == "name"


def test_ambiguous_names_are_recorded_without_fabricating_callers() -> None:
    table = make_table(
        {
            "a.py": """
        class A:
            def save(self): pass
        class B:
            def save(self): pass
        def use(obj): obj.save()
    """
        }
    )
    graph = build_call_graph(table)
    assert not graph.edges
    assert graph.unresolved == 1
    assert len(graph.ambiguous) == 1
    assert graph.ambiguous[0].source == "a.use"
    assert graph.ambiguous[0].candidates == ("a.A.save", "a.B.save")
    assert table.symbols["a.A.save"].called_by == []


def test_migration_rebuilds_resolution_and_preserves_notes(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "a.py").write_text("def f(): pass\ndef run(): f()\n", encoding="utf-8")
    apply_init(plan_init(root))
    scan(root)
    notes = root / ".aicontext/decisions.md"
    notes.write_bytes(b"Owner decision: preserve this note.\n")
    path = root / ".aicontext/manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["schema_version"] = "1.0"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    result = migrate(root)
    assert result["from"] == "1.0" and result["to"] == "1.1"
    assert result["steps"] == ["1.0 -> 1.1"]
    assert notes.read_bytes() == b"Owner decision: preserve this note.\n"
    graph = json.loads((root / ".aicontext/call_graph.json").read_text(encoding="utf-8"))
    assert graph["edges"][0]["resolution"] == "resolved"
    store = IndexStore.open(root)
    try:
        assert store.callers("a.f")[0].resolution == "resolved"
    finally:
        store.close()


@pytest.mark.parametrize("paused", [False, True])
def test_unconsented_migration_does_not_change_artifacts(tmp_path: Path, paused: bool) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "a.py").write_text("def f(): pass\n", encoding="utf-8")
    apply_init(plan_init(root))
    scan(root)
    entry = get_entry(root)
    assert entry is not None
    set_entry(root, RepoEntry(entry.repo_id, True, True) if paused else None)
    before = {
        p.relative_to(root): p.read_bytes() for p in (root / ".aicontext").rglob("*") if p.is_file()
    }
    with pytest.raises(NotEnabledError):
        migrate(root)
    assert before == {
        p.relative_to(root): p.read_bytes() for p in (root / ".aicontext").rglob("*") if p.is_file()
    }


def test_failed_rebuild_does_not_publish_new_schema(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    apply_init(plan_init(root))
    path = root / ".aicontext/manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["schema_version"] = "1.0"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    before = path.read_bytes()

    def fail(*args, **kwargs):
        raise RuntimeError("rebuild unavailable")

    monkeypatch.setattr("prism.lifecycle.scan", fail)
    with pytest.raises(RuntimeError, match="rebuild unavailable"):
        migrate(root)
    assert path.read_bytes() == before
