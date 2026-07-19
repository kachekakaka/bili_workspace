from __future__ import annotations

from pathlib import Path

from tools.check_markdown_links import find_broken_markdown_links


ROOT = Path(__file__).resolve().parent.parent


def test_markdown_internal_links_resolve() -> None:
    assert find_broken_markdown_links(ROOT) == []
