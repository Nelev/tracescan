"""taxonomy.md and the category list stay in step: every category has a definition and an example."""

import re
from pathlib import Path

from agent.diagnosis import FAILURE_CATEGORIES

TAXONOMY = Path(__file__).parent.parent / "agent" / "taxonomy.md"


def sections() -> dict[str, str]:
    """Heading to body, for each `## category` section of taxonomy.md."""
    parts = re.split(r"^## (.+)$", TAXONOMY.read_text(), flags=re.MULTILINE)
    return dict(zip(parts[1::2], parts[2::2], strict=True))


def test_every_category_has_a_section_and_every_section_is_a_category():
    assert list(sections()) == list(FAILURE_CATEGORIES)


def test_every_category_has_a_definition_and_an_example():
    for category, body in sections().items():
        for label in ("Definition", "Example"):
            match = re.search(rf"\*\*{label}\.\*\*\s*(\S.*)", body)
            assert match, f"{category} has no {label.lower()}"
