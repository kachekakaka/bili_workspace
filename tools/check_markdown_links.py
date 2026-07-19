from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parent.parent
_LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
_EXTERNAL_SCHEMES = {"data", "http", "https", "mailto", "tel"}
_IGNORED_DIRS = {".git", ".runtime", ".venv", "vendor"}


def _iter_markdown_files(root: Path):
    for path in root.rglob("*.md"):
        if any(part in _IGNORED_DIRS for part in path.relative_to(root).parts):
            continue
        if path.is_file() and not path.is_symlink():
            yield path


def _link_target(raw: str) -> str:
    value = raw.strip()
    if value.startswith("<") and ">" in value:
        return value[1 : value.index(">")]
    # Markdown allows an optional title after a whitespace-separated target.
    return value.split(maxsplit=1)[0]


def find_broken_markdown_links(root: Path = ROOT) -> list[str]:
    root = root.resolve()
    errors: list[str] = []
    for document in _iter_markdown_files(root):
        in_fence = False
        for line_number, line in enumerate(
            document.read_text(encoding="utf-8").splitlines(),
            start=1,
        ):
            stripped = line.lstrip()
            if stripped.startswith("```") or stripped.startswith("~~~"):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            for match in _LINK_RE.finditer(line):
                target = _link_target(match.group(1))
                if not target or target.startswith("#"):
                    continue
                parsed = urlsplit(target)
                if parsed.scheme.casefold() in _EXTERNAL_SCHEMES or parsed.netloc:
                    continue
                if parsed.path.startswith("/"):
                    # Root-relative web application routes are not repository files.
                    continue
                relative = Path(unquote(parsed.path))
                resolved = (document.parent / relative).resolve()
                try:
                    resolved.relative_to(root)
                except ValueError:
                    errors.append(
                        f"{document.relative_to(root)}:{line_number}: 链接越出仓库: {target}"
                    )
                    continue
                if not resolved.exists():
                    errors.append(
                        f"{document.relative_to(root)}:{line_number}: 目标不存在: {target}"
                    )
    return errors


def main() -> int:
    errors = find_broken_markdown_links()
    if errors:
        print("[失败] Markdown 内部链接检查发现问题：")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("[通过] Markdown 内部文件链接均可解析。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
