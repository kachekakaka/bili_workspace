#!/usr/bin/env python3
"""只读检查项目文档骨架、实际导航、生命周期、Registry 和归档。"""

from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from collections import Counter, deque
from pathlib import Path
from urllib.parse import unquote


ASSET_ID = "project-doc-skeleton/doc-consistency"
ASSET_SCHEMA = 1
IGNORED_PARTS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "venv",
}
REQUIRED_FILES = (
    "AGENTS.md",
    "README.md",
    "docs/README.md",
    "docs/需求文档.md",
    "docs/设计文档.md",
    "docs/已知问题与待做需求.md",
    "docs/软件测试.md",
    "SoftwareTesting/README.md",
    "SoftwareTesting/PROTOCOL.md",
    "SoftwareTesting/SAFETY.md",
    "SoftwareTesting/doc_consistency/README.md",
    "archive/docs/README.md",
)
REQUIRED_NAVIGATION = {
    "AGENTS.md": (
        ("README.md", "构建与交付"),
        ("docs/README.md", None),
        ("SoftwareTesting/README.md", None),
    ),
    "README.md": (
        ("docs/README.md", None),
        ("SoftwareTesting/README.md", None),
    ),
    "docs/README.md": (
        ("docs/需求文档.md", None),
        ("docs/设计文档.md", None),
        ("docs/已知问题与待做需求.md", None),
        ("docs/软件测试.md", None),
        ("archive/docs/README.md", None),
    ),
    "SoftwareTesting/README.md": (
        ("SoftwareTesting/PROTOCOL.md", None),
        ("SoftwareTesting/SAFETY.md", None),
        ("docs/软件测试.md", None),
        ("SoftwareTesting/doc_consistency/README.md", None),
    ),
}
MACHINE_FILES = (
    "AGENTS.md",
    "README.md",
    "docs/README.md",
    "docs/已知问题与待做需求.md",
    "docs/软件测试.md",
    "SoftwareTesting/README.md",
    "archive/docs/README.md",
    "archive/SoftwareTesting/README.md",
)
ALLOWED_BACKLOG_STATUSES = {"待确认", "待实施", "实施中", "暂缓"}
ALLOWED_PLAN_STATUSES = {"待确认", "实施中"}
PLAN_FIELDS = ("测试层级", "验证影响域", "具体验证项")
TEST_CATEGORIES = {"full", "affected_only", "explicit"}
BACKLOG_HEADING_RE = re.compile(
    r"^##\s+(?P<id>[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+)[：:]\s*(?P<title>.+?)\s*$"
)
BACKLOG_STATUS_RE = re.compile(r"^\s*[-*]\s*状态[：:]\s*(?P<status>\S.*?)\s*$")
TEST_ID_RE = re.compile(r"^T-[A-Z0-9]+(?:-[A-Z0-9]+)*$")
LINK_RE = re.compile(
    r"!?\[[^\]\n]*\]\(\s*"
    r"(?:<(?P<angle>[^>\n]+)>|(?P<plain>(?:\\.|[^()\s]|\([^()\n]*\))+))"
    r"(?:\s+(?:\"[^\"\n]*\"|'[^'\n]*'|\([^()\n]*\)))?\s*\)",
    re.IGNORECASE,
)
REFERENCE_LINK_RE = re.compile(r"(?<!!)\[[^\]\n]+\]\[[^\]\n]*\]")
HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$")
ABSOLUTE_USER_PATH_RE = re.compile(
    r"(?i)(?:[A-Z]:\\Users\\[^\\\s]+|/home/[^/\s]+/)"
)


def _ignored(path: Path, root: Path) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return True
    return any(part in IGNORED_PARTS for part in relative.parts)


def _is_archive(path: Path, root: Path) -> bool:
    try:
        return path.relative_to(root).parts[:1] == ("archive",)
    except ValueError:
        return False


def _is_within(path: Path, parent: Path) -> bool:
    candidate = path.resolve(strict=False)
    boundary = parent.resolve(strict=False)
    return candidate == boundary or boundary in candidate.parents


def _all_markdown(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file()
        and path.suffix.lower() == ".md"
        and not _ignored(path, root)
    )


def _active_markdown(root: Path) -> list[Path]:
    return [path for path in _all_markdown(root) if not _is_archive(path, root)]


def _checked_markdown(root: Path) -> list[Path]:
    files = _active_markdown(root)
    for relative in ("archive/docs/README.md", "archive/SoftwareTesting/README.md"):
        path = root / relative
        if path.is_file():
            files.append(path)
    return sorted(set(files))


def _strip_fenced_code(content: str) -> str:
    output: list[str] = []
    fence: str | None = None
    for line in content.splitlines(keepends=True):
        stripped = line.lstrip()
        marker = (
            "```"
            if stripped.startswith("```")
            else "~~~"
            if stripped.startswith("~~~")
            else None
        )
        if marker:
            if fence is None:
                fence = marker
            elif fence == marker:
                fence = None
            output.append("\n" if line.endswith(("\n", "\r")) else "")
        elif fence is None:
            output.append(line)
        else:
            output.append("\n" if line.endswith(("\n", "\r")) else "")
    return "".join(output)


def _slug_base(heading: str) -> str:
    value = re.sub(r"<[^>]+>", "", heading)
    value = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", value)
    value = value.replace("`", "").lower()
    kept: list[str] = []
    for char in value:
        category = unicodedata.category(char)
        if char in "-_ " or char.isspace():
            kept.append(char)
        elif category[0] in ("L", "N", "M"):
            kept.append(char)
    return re.sub(r"\s+", "-", "".join(kept))


def _heading_slugs(path: Path) -> set[str]:
    seen: dict[str, int] = {}
    result: set[str] = set()
    content = path.read_text(encoding="utf-8")
    for line in _strip_fenced_code(content).splitlines():
        match = HEADING_RE.match(line)
        if not match:
            continue
        base = _slug_base(match.group(1))
        index = seen.get(base, 0)
        slug = base if index == 0 else f"{base}-{index}"
        seen[base] = index + 1
        result.add(slug)
    return result


def _split_destination(raw: str) -> tuple[str, str]:
    value = raw.strip()
    if value.startswith("<") and value.endswith(">"):
        value = value[1:-1]
    path_part, separator, fragment = value.partition("#")
    return unquote(path_part), unquote(fragment).lower() if separator else ""


def _local_links(content: str, source: Path) -> list[tuple[str, Path, str]]:
    links: list[tuple[str, Path, str]] = []
    for match in LINK_RE.finditer(_strip_fenced_code(content)):
        raw = match.group("angle") or match.group("plain") or ""
        if re.match(r"^(?:[a-z][a-z0-9+.-]*:|//)", raw, re.IGNORECASE):
            continue
        path_part, fragment = _split_destination(raw)
        if not path_part and not fragment:
            continue
        target = source if not path_part else (source.parent / path_part).resolve(strict=False)
        links.append((raw, target, fragment))
    return links


def _line_number(content: str, position: int) -> int:
    return content.count("\n", 0, position) + 1


def _markdown_cells(line: str) -> list[str] | None:
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return None
    return [cell.strip() for cell in stripped[1:-1].split("|")]


def _is_separator(cells: list[str]) -> bool:
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells)


def _is_exact_file(root: Path, relative: str) -> bool:
    current = root
    for part in Path(relative).parts:
        if not current.is_dir():
            return False
        matches = [child for child in current.iterdir() if child.name == part]
        if len(matches) != 1:
            return False
        current = matches[0]
    return current.is_file()


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _check_required(root: Path, errors: list[str]) -> None:
    for relative in REQUIRED_FILES:
        if not _is_exact_file(root, relative):
            errors.append(f"{relative}: 缺少名称与大小写完全匹配的必需文件")


def _check_context_shape(root: Path, errors: list[str]) -> None:
    if (root / "CONTEXT-MAP.md").exists():
        errors.append("CONTEXT-MAP.md: 本骨架只支持单一上下文项目")
    nested = sorted(
        path
        for path in root.rglob("CONTEXT.md")
        if path.is_file()
        and path != root / "CONTEXT.md"
        and not _ignored(path, root)
    )
    for path in nested:
        errors.append(
            f"{path.relative_to(root).as_posix()}: 本骨架不允许嵌套 CONTEXT.md"
        )


def _check_markdown_files(root: Path, errors: list[str]) -> None:
    slug_cache: dict[Path, set[str]] = {}
    for path in _checked_markdown(root):
        relative = path.relative_to(root).as_posix()
        try:
            raw = path.read_bytes()
        except OSError as exc:
            errors.append(f"{relative}: 无法读取 Markdown: {exc}")
            continue
        if b"\r" in raw:
            errors.append(f"{relative}: 活动 Markdown 和归档索引必须使用 LF")
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError:
            errors.append(f"{relative}: 必须是有效 UTF-8")
            continue
        for destination, target, fragment in _local_links(content, path):
            if not target.exists():
                errors.append(f"{relative}: 链接目标不存在: {destination}")
                continue
            if fragment and target.is_file() and target.suffix.lower() == ".md":
                try:
                    slugs = slug_cache.setdefault(target, _heading_slugs(target))
                except (OSError, UnicodeDecodeError):
                    continue
                if fragment not in slugs:
                    errors.append(f"{relative}: 标题锚点不存在: {destination}")


def _direct_targets(path: Path) -> set[Path]:
    content = _read_text(path)
    if content is None:
        return set()
    return {
        target.resolve(strict=False)
        for _, target, _ in _local_links(content, path)
    }


def _check_navigation(root: Path, errors: list[str]) -> None:
    navigation = dict(REQUIRED_NAVIGATION)
    if _is_exact_file(root, "CONTEXT.md"):
        navigation["AGENTS.md"] = (
            ("CONTEXT.md", None),
            *navigation["AGENTS.md"],
        )

    for source_relative, expected in navigation.items():
        source = root / source_relative
        if not source.is_file():
            continue
        content = _read_text(source)
        if content is None:
            continue
        links = _local_links(content, source)
        if source_relative == "README.md":
            agents = (root / "AGENTS.md").resolve(strict=False)
            if any(linked_target == agents for _, linked_target, _ in links):
                errors.append(
                    "README.md: 不得反向链接 AGENTS.md；AGENTS.md 是协作第一入口"
                )
        for target_relative, heading in expected:
            target = (root / target_relative).resolve(strict=False)
            expected_fragment = _slug_base(heading) if heading else None
            if not any(
                linked_target == target
                and (expected_fragment is None or fragment == expected_fragment)
                for _, linked_target, fragment in links
            ):
                suffix = f"#{expected_fragment}" if expected_fragment else ""
                errors.append(
                    f"{source_relative}: 缺少必要入口 {target_relative}{suffix}"
                )


def _markdown_graph(root: Path) -> dict[Path, set[Path]]:
    active = {path.resolve(strict=False) for path in _active_markdown(root)}
    graph: dict[Path, set[Path]] = {}
    for path in sorted(active):
        content = _read_text(path)
        targets: set[Path] = set()
        if content is not None:
            for _, target, _ in _local_links(content, path):
                candidate = target
                if candidate.is_dir():
                    candidate = candidate / "README.md"
                resolved = candidate.resolve(strict=False)
                if resolved in active:
                    targets.add(resolved)
        graph[path] = targets
    return graph


def _reachable_within(
    graph: dict[Path, set[Path]],
    start: Path,
    max_hops: int,
) -> set[Path]:
    start = start.resolve(strict=False)
    reached = {start}
    queue: deque[tuple[Path, int]] = deque([(start, 0)])
    while queue:
        current, depth = queue.popleft()
        if depth >= max_hops:
            continue
        for target in graph.get(current, set()):
            if target in reached:
                continue
            reached.add(target)
            queue.append((target, depth + 1))
    return reached


def _check_docs_reachability(root: Path, errors: list[str]) -> None:
    index = root / "docs" / "README.md"
    docs_root = root / "docs"
    if not index.is_file() or not docs_root.is_dir():
        return
    graph = _markdown_graph(root)
    reached = _reachable_within(graph, index, 2)
    for path in sorted(docs_root.rglob("*.md")):
        if path == index or _ignored(path, root):
            continue
        if path.resolve(strict=False) not in reached:
            errors.append(
                f"{path.relative_to(root).as_posix()}: "
                "活动文档不能从 docs/README.md 通过两次实际 Markdown 链接到达"
            )


def _suite_readmes(root: Path) -> list[Path]:
    testing_root = root / "SoftwareTesting"
    if not testing_root.is_dir():
        return []
    return sorted(
        path
        for path in testing_root.rglob("README.md")
        if path != testing_root / "README.md" and not _ignored(path, root)
    )


def _check_suite_navigation(root: Path, errors: list[str]) -> None:
    index = root / "SoftwareTesting" / "README.md"
    if not index.is_file():
        return
    direct = _direct_targets(index)
    for path in _suite_readmes(root):
        if path.resolve(strict=False) not in direct:
            errors.append(
                f"{path.relative_to(root).as_posix()}: "
                "活动 suite README 必须从 SoftwareTesting/README.md 直接链接"
            )


def _parse_backlog(
    root: Path,
    errors: list[str],
) -> tuple[dict[str, str], dict[str, set[Path]]]:
    path = root / "docs" / "已知问题与待做需求.md"
    content = _read_text(path)
    if content is None:
        return {}, {}
    lines = _strip_fenced_code(content).splitlines()
    result: dict[str, str] = {}
    plan_targets: dict[str, set[Path]] = {}
    seen_ids: set[str] = set()
    index = 0
    while index < len(lines):
        heading = BACKLOG_HEADING_RE.match(lines[index])
        if not heading:
            if lines[index].startswith("## "):
                errors.append(
                    "docs/已知问题与待做需求.md: "
                    "所有二级标题必须使用“待办ID：标题”格式"
                )
            index += 1
            continue

        item_id = heading.group("id")
        if item_id in seen_ids:
            errors.append(f"docs/已知问题与待做需求.md: 待办 ID 重复: {item_id}")
        seen_ids.add(item_id)

        statuses: list[str] = []
        index += 1
        section_start = index
        while index < len(lines) and not lines[index].startswith("## "):
            status_match = BACKLOG_STATUS_RE.match(lines[index])
            if status_match:
                statuses.append(status_match.group("status"))
            index += 1
        section = "\n".join(lines[section_start:index])
        plan_targets.setdefault(item_id, set()).update(
            target.resolve(strict=False)
            for _, target, _ in _local_links(section, path)
        )
        if len(statuses) != 1:
            errors.append(
                f"docs/已知问题与待做需求.md: {item_id} 必须且只能有一个状态"
            )
            continue
        status = statuses[0]
        if status not in ALLOWED_BACKLOG_STATUSES:
            errors.append(
                f"docs/已知问题与待做需求.md: {item_id} 使用非法状态: {status}"
            )
            continue
        result[item_id] = status
    return result, plan_targets


def _check_plans(
    root: Path,
    backlog: dict[str, str],
    backlog_plan_targets: dict[str, set[Path]],
    errors: list[str],
) -> None:
    plans_root = root / "docs" / "方案"
    by_id: dict[str, list[Path]] = {}

    if plans_root.exists() and not plans_root.is_dir():
        errors.append("docs/方案: 必须是目录")
        return
    if plans_root.is_dir():
        entries = sorted(plans_root.iterdir())
        if not entries:
            errors.append("docs/方案: 条件目录为空时不应存在")
        for path in entries:
            if not path.is_file() or path.suffix.lower() != ".md":
                errors.append(
                    f"{path.relative_to(root).as_posix()}: "
                    "活动方案目录只允许直接放置 Markdown 文件"
                )
                continue
            matches = sorted(
                (
                    item_id
                    for item_id in backlog
                    if path.name.startswith(f"{item_id}-")
                ),
                key=len,
                reverse=True,
            )
            if not matches:
                errors.append(
                    f"{path.relative_to(root).as_posix()}: "
                    "文件名必须以有效待办 ID 和连字符开头"
                )
                continue
            item_id = matches[0]
            if not path.stem.removeprefix(f"{item_id}-"):
                errors.append(
                    f"{path.relative_to(root).as_posix()}: "
                    "待办 ID 后必须包含方案名称"
                )
            by_id.setdefault(item_id, []).append(path)
            if backlog[item_id] not in ALLOWED_PLAN_STATUSES:
                errors.append(
                    f"{path.relative_to(root).as_posix()}: "
                    f"对应待办 {item_id} 的状态“{backlog[item_id]}”不允许活动方案"
                )
            if path.resolve(strict=False) not in backlog_plan_targets.get(item_id, set()):
                errors.append(
                    f"{path.relative_to(root).as_posix()}: "
                    "必须由对应待办条目实际链接"
                )
            content = _read_text(path)
            if content is None:
                continue
            stripped = _strip_fenced_code(content)
            for field in PLAN_FIELDS:
                count = len(
                    re.findall(
                        rf"(?m)^\s*(?:[-*]\s*)?{re.escape(field)}\s*[：:]",
                        stripped,
                    )
                )
                if count != 1:
                    errors.append(
                        f"{path.relative_to(root).as_posix()}: "
                        f"{field} 必须且只能出现一次"
                    )

    for item_id, paths in sorted(by_id.items()):
        if len(paths) > 1:
            errors.append(f"docs/方案/: 待办 {item_id} 存在多份活动方案")
    for item_id, status in sorted(backlog.items()):
        count = len(by_id.get(item_id, []))
        if status == "实施中" and count != 1:
            errors.append(
                f"docs/方案/: 实施中待办 {item_id} 必须有且只有一份活动方案"
            )
        if status not in ALLOWED_PLAN_STATUSES and count:
            errors.append(
                f"docs/方案/: 状态为“{status}”的待办 {item_id} 不得有活动方案"
            )


def _parse_registry(
    root: Path,
    errors: list[str],
) -> dict[str, tuple[str, Path, str]]:
    path = root / "docs" / "软件测试.md"
    content = _read_text(path)
    if content is None:
        return {}
    lines = _strip_fenced_code(content).splitlines()
    expected_header = ["ID", "执行类别", "入口", "唯一职责"]
    headers = [
        index
        for index, line in enumerate(lines)
        if _markdown_cells(line) == expected_header
    ]
    if len(headers) != 1:
        errors.append("docs/软件测试.md: 必须且只能有一张四列活动测试项表")
        return {}
    start = headers[0]
    if start + 1 >= len(lines):
        errors.append("docs/软件测试.md: Registry 缺少分隔行")
        return {}
    separator = _markdown_cells(lines[start + 1])
    if separator is None or len(separator) != 4 or not _is_separator(separator):
        errors.append("docs/软件测试.md: Registry 分隔行无效")
        return {}

    entries: dict[str, tuple[str, Path, str]] = {}
    row_count = 0
    for line_number in range(start + 2, len(lines)):
        cells = _markdown_cells(lines[line_number])
        if cells is None:
            break
        if len(cells) != 4:
            errors.append(
                f"docs/软件测试.md:{line_number + 1}: Registry 行必须恰好四列"
            )
            continue
        item_id = cells[0].strip("` ")
        category = cells[1].strip("` ")
        if not TEST_ID_RE.fullmatch(item_id):
            errors.append(
                f"docs/软件测试.md:{line_number + 1}: 非法测试项 ID: {item_id}"
            )
        elif item_id in entries:
            errors.append(f"docs/软件测试.md: 测试项 ID 重复: {item_id}")
        if category not in TEST_CATEGORIES:
            errors.append(
                f"docs/软件测试.md:{line_number + 1}: 非法执行类别: {category}"
            )
        entry_links = _local_links(cells[2], path)
        if len(entry_links) != 1:
            errors.append(
                f"docs/软件测试.md:{line_number + 1}: "
                "入口必须恰好包含一个普通行内本地链接"
            )
            entry_target = path
        else:
            entry_target = entry_links[0][1]
        if not cells[3]:
            errors.append(
                f"docs/软件测试.md:{line_number + 1}: 唯一职责不能为空"
            )
        if TEST_ID_RE.fullmatch(item_id) and item_id not in entries:
            entries[item_id] = (category, entry_target, cells[3])
        row_count += 1

    if row_count == 0:
        errors.append("docs/软件测试.md: Registry 至少登记 T-DOC")

    doc_entry = entries.get("T-DOC")
    expected_doc_target = (
        root / "SoftwareTesting" / "doc_consistency" / "README.md"
    ).resolve(strict=False)
    if doc_entry is None:
        errors.append("docs/软件测试.md: Registry 缺少必需测试项 T-DOC")
    else:
        if doc_entry[0] != "full":
            errors.append("docs/软件测试.md: T-DOC 的执行类别必须是 full")
        if doc_entry[1].resolve(strict=False) != expected_doc_target:
            errors.append(
                "docs/软件测试.md: T-DOC 必须指向 "
                "SoftwareTesting/doc_consistency/README.md"
            )

    return entries


def _check_suite_registry(
    root: Path,
    entries: dict[str, tuple[str, Path, str]],
    errors: list[str],
) -> None:
    registry_targets = {
        target.resolve(strict=False)
        for _, target, _ in entries.values()
    }
    for path in _suite_readmes(root):
        if path.resolve(strict=False) not in registry_targets:
            errors.append(
                f"{path.relative_to(root).as_posix()}: "
                "活动 suite README 必须由 Registry 测试项链接"
            )


def _archive_table(
    index: Path,
    errors: list[str],
    root: Path,
) -> list[tuple[int, list[str]]]:
    content = _read_text(index)
    if content is None:
        return []
    lines = _strip_fenced_code(content).splitlines()
    header = ["归档文档", "历史职责", "当前承接真源"]
    headers = [
        position
        for position, line in enumerate(lines)
        if _markdown_cells(line) == header
    ]
    relative = index.relative_to(root).as_posix()
    if len(headers) != 1:
        errors.append(f"{relative}: 必须且只能有一张三列归档索引表")
        return []
    start = headers[0]
    if start + 1 >= len(lines):
        errors.append(f"{relative}: 归档索引缺少分隔行")
        return []
    separator = _markdown_cells(lines[start + 1])
    if separator is None or len(separator) != 3 or not _is_separator(separator):
        errors.append(f"{relative}: 归档索引分隔行无效")
        return []

    rows: list[tuple[int, list[str]]] = []
    for position in range(start + 2, len(lines)):
        cells = _markdown_cells(lines[position])
        if cells is None:
            break
        rows.append((position + 1, cells))
    return rows


def _check_archive_area(root: Path, relative: str, errors: list[str]) -> None:
    archive_root = root / relative
    if not archive_root.exists():
        return
    index = archive_root / "README.md"
    if not index.is_file():
        errors.append(f"{relative}/README.md: 归档目录缺少索引")
        return

    rows = _archive_table(index, errors, root)
    targets: list[Path] = []
    for line_number, cells in rows:
        index_relative = index.relative_to(root).as_posix()
        if len(cells) != 3:
            errors.append(
                f"{index_relative}:{line_number}: 归档条目必须恰好三列"
            )
            continue
        document_links = _local_links(cells[0], index)
        if len(document_links) != 1:
            errors.append(
                f"{index_relative}:{line_number}: "
                "归档文档列必须恰好有一个普通行内本地链接"
            )
            continue
        target = document_links[0][1]
        if (
            target == index
            or not target.is_file()
            or target.suffix.lower() != ".md"
            or not _is_within(target, archive_root)
        ):
            errors.append(
                f"{index_relative}:{line_number}: 归档链接必须指向本归档区 Markdown"
            )
        targets.append(target)
        if not cells[1].strip():
            errors.append(
                f"{index_relative}:{line_number}: 历史职责不能为空"
            )

        no_current = cells[2].strip() == "无，仅保留历史证据"
        current_links = _local_links(cells[2], index)
        valid_current = (
            len(current_links) == 1
            and current_links[0][1].is_file()
            and current_links[0][1].suffix.lower() == ".md"
            and _is_within(current_links[0][1], root)
            and not _is_archive(current_links[0][1], root)
        )
        if not no_current and not valid_current:
            errors.append(
                f"{index_relative}:{line_number}: "
                "当前承接真源必须链接一个项目内活动 Markdown，"
                "或精确写“无，仅保留历史证据”"
            )

    counts = Counter(target.resolve(strict=False) for target in targets)
    archived = sorted(
        path
        for path in archive_root.rglob("*.md")
        if path != index and not _ignored(path, root)
    )
    for path in archived:
        count = counts[path.resolve(strict=False)]
        if count != 1:
            errors.append(
                f"{path.relative_to(root).as_posix()}: "
                f"必须由归档索引恰好登记一次，实际 {count}"
            )
    for target, count in counts.items():
        if count > 1:
            try:
                target_relative = target.relative_to(root).as_posix()
            except ValueError:
                target_relative = str(target)
            errors.append(f"{target_relative}: 归档索引重复登记 {count} 次")


def _check_archive_navigation(root: Path, errors: list[str]) -> None:
    navigation_files = (
        "AGENTS.md",
        "README.md",
        "docs/README.md",
        "SoftwareTesting/README.md",
    )
    allowed = {
        (root / "archive/docs/README.md").resolve(strict=False),
        (root / "archive/SoftwareTesting/README.md").resolve(strict=False),
    }
    for relative in navigation_files:
        path = root / relative
        content = _read_text(path)
        if content is None:
            continue
        for raw, target, _ in _local_links(content, path):
            if _is_archive(target, root) and target not in allowed:
                errors.append(
                    f"{relative}: 活动导航不得直接链接归档正文: {raw}"
                )


def _check_machine_syntax(root: Path, warnings: list[str]) -> None:
    for relative in MACHINE_FILES:
        path = root / relative
        content = _read_text(path)
        if content is None:
            continue
        stripped = _strip_fenced_code(content)
        for match in REFERENCE_LINK_RE.finditer(stripped):
            warnings.append(
                f"{relative}:{_line_number(stripped, match.start())}: "
                "机器入口使用引用式链接，无法保证机械解析"
            )
        if relative in {
            "docs/软件测试.md",
            "archive/docs/README.md",
            "archive/SoftwareTesting/README.md",
        }:
            for number, line in enumerate(stripped.splitlines(), start=1):
                if line.strip().startswith("|") and r"\|" in line:
                    warnings.append(
                        f"{relative}:{number}: "
                        "机器表格包含转义竖线，简单解析器无法保证结果"
                    )


def _check_absolute_paths(root: Path, warnings: list[str]) -> None:
    for path in _active_markdown(root):
        content = _read_text(path)
        if content is None:
            continue
        stripped = _strip_fenced_code(content)
        relative = path.relative_to(root).as_posix()
        for match in ABSOLUTE_USER_PATH_RE.finditer(stripped):
            warnings.append(
                f"{relative}:{_line_number(stripped, match.start())}: "
                "发现绝对本地用户路径，检查文档可移植性"
            )


def _check_navigation_overlap(root: Path, warnings: list[str]) -> None:
    readme = root / "README.md"
    docs_index = root / "docs" / "README.md"
    if not readme.is_file() or not docs_index.is_file():
        return
    docs_root = root / "docs"
    shared = sorted(
        target
        for target in _direct_targets(readme) & _direct_targets(docs_index)
        if target.is_file()
        and target.suffix.lower() == ".md"
        and _is_within(target, docs_root)
        and target != docs_index.resolve(strict=False)
    )
    if len(shared) < 3:
        return
    paths = ", ".join(path.relative_to(root).as_posix() for path in shared)
    warnings.append(
        "README.md: 与 docs/README.md 重复直接链接 "
        f"{len(shared)} 份专题 Markdown，复核根入口是否重复枚举: {paths}"
    )


def collect_doc_consistency(
    root: Path | None = None,
) -> tuple[list[str], list[str]]:
    workspace = (root or Path(__file__).resolve().parents[2]).resolve()
    errors: list[str] = []
    warnings: list[str] = []
    _check_required(workspace, errors)
    _check_context_shape(workspace, errors)
    _check_markdown_files(workspace, errors)
    _check_navigation(workspace, errors)
    _check_docs_reachability(workspace, errors)
    _check_suite_navigation(workspace, errors)
    backlog, backlog_plan_targets = _parse_backlog(workspace, errors)
    _check_plans(workspace, backlog, backlog_plan_targets, errors)
    entries = _parse_registry(workspace, errors)
    _check_suite_registry(workspace, entries, errors)
    _check_archive_area(workspace, "archive/docs", errors)
    _check_archive_area(workspace, "archive/SoftwareTesting", errors)
    _check_archive_navigation(workspace, errors)
    _check_machine_syntax(workspace, warnings)
    _check_absolute_paths(workspace, warnings)
    _check_navigation_overlap(workspace, warnings)
    return errors, warnings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-root", type=Path)
    args = parser.parse_args()
    errors, warnings = collect_doc_consistency(args.workspace_root)
    for warning in warnings:
        print(f"[WARN] {warning}")
    if errors:
        for error in errors:
            print(f"[FAIL] {error}")
        print(f"FAILED: {len(errors)} issue(s), {len(warnings)} warning(s)")
        return 1
    print(f"文档机械一致性检查通过（{len(warnings)} warning(s)）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
