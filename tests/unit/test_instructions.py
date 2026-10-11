from prism.hooks.prompt import HEADER
from prism.instructions import CONSENT, QUOTED_DATA, SHORT, long_form
from prism.integrations.common import SKILL_NAMES, skill_description, skill_text
from prism.mcp.server import INSTRUCTIONS


def test_shared_rules_and_standing_budget() -> None:
    assert HEADER == INSTRUCTIONS == SHORT
    for mcp, previous_words in ((False, 177), (True, 203)):
        block = long_form(mcp)
        assert SHORT in block and CONSENT in block and QUOTED_DATA in block
        assert len((HEADER + INSTRUCTIONS + block).split()) <= previous_words * 0.7
        assert ("prism_task" in block) == mcp
    context = skill_text("prism-context")
    assert SHORT in context and CONSENT in context and QUOTED_DATA in context


def test_skill_listing_and_explicit_workflows() -> None:
    for name in SKILL_NAMES:
        text = skill_text(name)
        assert len(skill_description(name)) < 300
        assert len(text.splitlines()) < 500
        assert ("disable-model-invocation: true" in text) == (name != "prism-context")
