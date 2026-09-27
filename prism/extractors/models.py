"""Data models: ORM / schema classes, their fields, and who uses them."""

from __future__ import annotations

from prism.core.models import ModelInfo
from prism.extractors.base import Extractor, ExtractorContext
from prism.graph.call_graph import Resolver

_MODEL_MODULE_HINTS = ("model", "schema", "entity", "entities")


def _framework(
    bases: list[str], decorators: list[str], externals: set[str], module: str
) -> str | None:
    for base in bases:
        leaf = base.rsplit(".", 1)[-1]
        if base in ("models.Model", "django.db.models.Model"):
            return "django"
        if leaf == "SQLModel":
            return "sqlmodel"
        if leaf == "BaseModel" and "pydantic" in externals:
            return "pydantic"
        if leaf in ("DeclarativeBase", "Base") and "sqlalchemy" in externals:
            return "sqlalchemy"
        if base in ("db.Model",):
            return "sqlalchemy"
        if leaf == "Document" and ("mongoengine" in externals or "beanie" in externals):
            return "odm"
    is_dataclass = any(d.split("(")[0].rsplit(".", 1)[-1] == "dataclass" for d in decorators)
    if is_dataclass and any(h in module.rsplit(".", 1)[-1] for h in _MODEL_MODULE_HINTS):
        return "dataclass"
    return None


class ModelsExtractor(Extractor[list[ModelInfo]]):
    name = "models"

    def run(self, ctx: ExtractorContext) -> list[ModelInfo]:
        table = ctx.table
        found: list[ModelInfo] = []
        model_ids: set[str] = set()
        for mod, pf in sorted(table.files.items()):
            externals = set(ctx.import_graph.modules[mod].external)
            for ps in pf.symbols:
                if ps.kind != "class":
                    continue
                framework = _framework(ps.bases, ps.decorators, externals, mod)
                if framework is None:
                    continue
                sid = f"{mod}.{ps.qualname}"
                model_ids.add(sid)
                found.append(ModelInfo(sid, pf.path, ps.lines, framework, list(ps.fields), []))
        # Subclasses of a detected model are models too (e.g. an app-level Base).
        resolver = Resolver(table)
        for mod, pf in sorted(table.files.items()):
            for ps in pf.symbols:
                sid = f"{mod}.{ps.qualname}"
                if ps.kind != "class" or sid in model_ids or not ps.bases:
                    continue
                parents = {resolver.resolve_name(mod, b) for b in ps.bases}
                parent_models = [m for m in found if m.id in parents]
                if parent_models:
                    model_ids.add(sid)
                    found.append(
                        ModelInfo(
                            sid, pf.path, ps.lines, parent_models[0].framework, list(ps.fields), []
                        )
                    )
        for info in found:
            info.used_by = sorted(table.symbols[info.id].called_by)
        return sorted(found, key=lambda m: m.id)
