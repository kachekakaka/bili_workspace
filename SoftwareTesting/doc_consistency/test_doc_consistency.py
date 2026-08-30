#!/usr/bin/env python3
"""只读检查活动文档和归档文档的稳定机械关系。"""

from __future__ import annotations

import argparse
import os
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote


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
PROJECT_SKILL_ROOTS = frozenset(
    {
        (".agents", "skills"),
        (".claude", "skills"),
        (".codex", "skills"),
        (".cursor", "skills"),
        (".github", "skills"),
        (".opencode", "skill"),
        (".opencode", "skills"),
    }
)
REQUIRED_FILES = (
    "AGENTS.md",
    "README.md",
    "docs/README.md",
    "docs/已知问题与待做需求.md",
    "docs/软件测试.md",
    "SoftwareTesting/README.md",
    "SoftwareTesting/doc_consistency/README.md",
    "SoftwareTesting/archive_consistency/README.md",
)
REQUIRED_LINKS = {
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
        ("docs/已知问题与待做需求.md", None),
        ("docs/软件测试.md", None),
    ),
    "SoftwareTesting/README.md": (
        ("docs/软件测试.md", None),
        ("SoftwareTesting/doc_consistency/README.md", None),
        ("SoftwareTesting/archive_consistency/README.md", None),
    ),
}
ARCHIVE_AREAS = ("archive/docs", "archive/SoftwareTesting")
ALLOWED_BACKLOG_STATUSES = {"待确认", "待实施", "实施中", "暂缓"}
PLAN_REQUIRED_STATUSES = {"待实施", "实施中"}
PLAN_FIELDS = ("测试层级", "验证影响域", "具体验证项")
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
HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$")


@dataclass(frozen=True)
class BacklogItem:
    status: str
    linked_plans: frozenset[Path]


def _is_project_skill_asset(path: Path, root: Path) -> bool:
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        return False
    return any(
        parts[index : index + 2] in PROJECT_SKILL_ROOTS
        for index in range(len(parts) - 1)
    )


def _ignored(path: Path, root: Path) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return True
    return _is_project_skill_asset(path, root) or any(
        part in IGNORED_PARTS for part in relative.parts
    )


def _is_within(path: Path, parent: Path) -> bool:
    candidate = path.resolve(strict=False)
    boundary = parent.resolve(strict=False)
    return candidate == boundary or boundary in candidate.parents


def _walk_markdown(root: Path, start: Path, *, exclude_archive: bool) -> tuple[Path, ...]:
    if not start.is_dir():
        return ()
    files: list[Path] = []
    for current, directory_names, file_names in os.walk(start, topdown=True):
        current_path = Path(current)
        directory_names[:] = sorted(
            name
            for name in directory_names
            if not _ignored(current_path / name, root)
            and not (
                exclude_archive
                and current_path == root
                and name == "archive"
            )
        )
        files.extend(
            current_path / name
            for name in sorted(file_names)
            if (current_path / name).suffix.lower() == ".md"
            and not _ignored(current_path / name, root)
        )
    return tuple(sorted(files))


def _strip_fenced_code(content: str) -> str:
    output: list[str] = []
    fence: str | None = None
    for line in content.splitlines(keepends=True):
        stripped = line.lstrip()
        marker = "```" if stripped.startswith("```") else "~~~" if stripped.startswith("~~~") else None
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
        result.add(base if index == 0 else f"{base}-{index}")
        seen[base] = index + 1
    return result


def _local_links(content: str, source: Path) -> list[tuple[str, Path, str]]:
    links: list[tuple[str, Path, str]] = []
    for match in LINK_RE.finditer(_strip_fenced_code(content)):
        raw = match.group("angle") or match.group("plain") or ""
        if re.match(r"^(?:[a-z][a-z0-9+.-]*:|//)", raw, re.IGNORECASE):
            continue
        path_part, separator, fragment = raw.strip().partition("#")
        path_part = unquote(path_part.strip("<>"))
        fragment = unquote(fragment).lower() if separator else ""
        if not path_part and not fragment:
            continue
        target = source if not path_part else (source.parent / path_part).resolve(strict=False)
        links.append((raw, target, fragment))
    return links


def _markdown_cells(line: str) -> list[str] | None:
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return None
    return [cell.strip() for cell in stripped[1:-1].split("|")]


def _is_separator(cells: list[str]) -> bool:
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells)


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _check_required_files(root: Path, errors: list[str]) -> None:
    for relative in REQUIRED_FILES:
        if not (root / relative).is_file():
            errors.append(f"{relative}: 缺少必要入口文件")


def _check_markdown_files(root: Path, paths: tuple[Path, ...], errors: list[str]) -> None:
    slug_cache: dict[Path, set[str]] = {}
    for path in paths:
        relative = path.relative_to(root).as_posix()
        try:
            raw = path.read_bytes()
        except OSError as exc:
            errors.append(f"{relative}: 无法读取 Markdown: {exc}")
            continue
        if b"\r" in raw:
            errors.append(f"{relative}: Markdown 必须使用 LF")
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError:
            errors.append(f"{relative}: Markdown 必须是有效 UTF-8")
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


def _check_required_links(root: Path, errors: list[str]) -> None:
    links = dict(REQUIRED_LINKS)
    if (root / "CONTEXT.md").is_file():
        links["AGENTS.md"] = (("CONTEXT.md", None), *links["AGENTS.md"])
    for source_relative, expected in links.items():
        source = root / source_relative
        content = _read_text(source)
        if content is None:
            continue
        actual = _local_links(content, source)
        for target_relative, heading in expected:
            target = (root / target_relative).resolve(strict=False)
            fragment = _slug_base(heading) if heading else None
            if not any(
                linked_target == target and (fragment is None or linked_fragment == fragment)
                for _, linked_target, linked_fragment in actual
            ):
                suffix = f"#{fragment}" if fragment else ""
                errors.append(f"{source_relative}: 缺少必要入口 {target_relative}{suffix}")


def _parse_backlog(root: Path, errors: list[str]) -> dict[str, BacklogItem]:
    path = root / "docs" / "已知问题与待做需求.md"
    content = _read_text(path)
    if content is None:
        return {}
    lines = _strip_fenced_code(content).splitlines()
    items: dict[str, BacklogItem] = {}
    seen_ids: set[str] = set()
    index = 0
    while index < len(lines):
        heading = BACKLOG_HEADING_RE.match(lines[index])
        if not heading:
            index += 1
            continue
        item_id = heading.group("id")
        index += 1
        section_start = index
        statuses: list[str] = []
        while index < len(lines) and not lines[index].startswith("## "):
            status_match = BACKLOG_STATUS_RE.match(lines[index])
            if status_match:
                statuses.append(status_match.group("status"))
            index += 1
        section = "\n".join(lines[section_start:index])
        linked_plans = frozenset(
            target.resolve(strict=False)
            for _, target, _ in _local_links(section, path)
            if _is_within(target, root / "docs" / "方案")
        )
        if item_id in seen_ids:
            errors.append(f"docs/已知问题与待做需求.md: 待办 ID 重复: {item_id}")
            continue
        seen_ids.add(item_id)
        if len(statuses) != 1:
            errors.append(f"docs/已知问题与待做需求.md: {item_id} 必须且只能有一个状态")
            continue
        status = statuses[0]
        if status not in ALLOWED_BACKLOG_STATUSES:
            errors.append(f"docs/已知问题与待做需求.md: {item_id} 使用非法状态: {status}")
            continue
        items[item_id] = BacklogItem(status=status, linked_plans=linked_plans)
    return items


def _check_plan_fields(path: Path, root: Path, errors: list[str]) -> None:
    content = _read_text(path)
    if content is None:
        return
    stripped = _strip_fenced_code(content)
    for field in PLAN_FIELDS:
        count = len(re.findall(rf"(?m)^\s*(?:[-*]\s*)?{re.escape(field)}\s*[：:]", stripped))
        if count != 1:
            errors.append(
                f"{path.relative_to(root).as_posix()}: {field} 必须且只能出现一次"
            )


def _check_plans(root: Path, items: dict[str, BacklogItem], errors: list[str]) -> None:
    plans_root = root / "docs" / "方案"
    plans = tuple(sorted(plans_root.glob("*.md"))) if plans_root.is_dir() else ()
    by_id: dict[str, list[Path]] = {item_id: [] for item_id in items}
    for path in plans:
        matches = sorted(
            (item_id for item_id in items if path.name.startswith(f"{item_id}-")),
            key=len,
            reverse=True,
        )
        if not matches:
            errors.append(
                f"{path.relative_to(root).as_posix()}: 活动方案文件名没有对应待办 ID"
            )
            continue
        item_id = matches[0]
        by_id[item_id].append(path)
        item = items[item_id]
        if path.resolve(strict=False) not in item.linked_plans:
            errors.append(
                f"{path.relative_to(root).as_posix()}: 必须由对应待办条目链接"
            )
        _check_plan_fields(path, root, errors)

    for item_id, item in sorted(items.items()):
        plans_for_item = by_id[item_id]
        if len(plans_for_item) > 1:
            errors.append(f"docs/方案/: 待办 {item_id} 存在多份活动方案")
        if item.status in PLAN_REQUIRED_STATUSES and len(plans_for_item) != 1:
            errors.append(
                f"docs/方案/: {item.status}待办 {item_id} 必须有且只有一份活动方案"
            )
        if item.status == "暂缓" and plans_for_item:
            errors.append(f"docs/方案/: 暂缓待办 {item_id} 不得保留活动方案")


def _find_table(lines: list[str], required_headers: set[str]) -> tuple[list[str], list[list[str]]] | None:
    for index, line in enumerate(lines):
        header = _markdown_cells(line)
        if header is None or not required_headers.issubset(set(header)):
            continue
        if index + 1 >= len(lines):
            return header, []
        separator = _markdown_cells(lines[index + 1])
        if separator is None or len(separator) != len(header) or not _is_separator(separator):
            return header, []
        rows: list[list[str]] = []
        for row_line in lines[index + 2 :]:
            cells = _markdown_cells(row_line)
            if cells is None:
                break
            rows.append(cells)
        return header, rows
    return None


def _check_registry(root: Path, errors: list[str]) -> None:
    path = root / "docs" / "软件测试.md"
    content = _read_text(path)
    if content is None:
        return
    table = _find_table(_strip_fenced_code(content).splitlines(), {"ID", "入口"})
    if table is None:
        errors.append("docs/软件测试.md: 缺少包含 ID 和入口列的 Registry 表")
        return
    header, rows = table
    if not rows:
        errors.append("docs/软件测试.md: Registry 不能为空")
        return
    id_index = header.index("ID")
    entry_index = header.index("入口")
    entries: dict[str, Path] = {}
    seen_ids: set[str] = set()
    for cells in rows:
        if len(cells) != len(header):
            errors.append("docs/软件测试.md: Registry 行列数与表头不一致")
            continue
        item_id = cells[id_index].strip("` ")
        if not TEST_ID_RE.fullmatch(item_id):
            errors.append(f"docs/软件测试.md: 非法测试项 ID: {item_id}")
            continue
        if item_id in seen_ids:
            errors.append(f"docs/软件测试.md: 测试项 ID 重复: {item_id}")
            continue
        seen_ids.add(item_id)
        entry_links = _local_links(cells[entry_index], path)
        if len(entry_links) != 1:
            errors.append(f"docs/软件测试.md: {item_id} 的入口必须包含一个本地链接")
            continue
        entries[item_id] = entry_links[0][1]

    required = {
        "T-DOC": root / "SoftwareTesting" / "doc_consistency" / "README.md",
        "T-ARCHIVE": root / "SoftwareTesting" / "archive_consistency" / "README.md",
    }
    for item_id, expected in required.items():
        actual = entries.get(item_id)
        if actual is None:
            errors.append(f"docs/软件测试.md: Registry 缺少必需测试项 {item_id}")
        elif actual.resolve(strict=False) != expected.resolve(strict=False):
            errors.append(f"docs/软件测试.md: {item_id} 的入口不正确")


def _check_archive_area(root: Path, area: Path, paths: tuple[Path, ...], errors: list[str]) -> None:
    if not area.exists():
        return
    index = area / "README.md"
    content = _read_text(index)
    if content is None:
        errors.append(f"{index.relative_to(root).as_posix()}: 归档区缺少可读索引")
        return
    table = _find_table(
        _strip_fenced_code(content).splitlines(),
        {"归档文档", "当前承接真源"},
    )
    if table is None:
        errors.append(f"{index.relative_to(root).as_posix()}: 缺少归档索引表")
        return
    header, rows = table
    document_index = header.index("归档文档")
    current_index = header.index("当前承接真源")
    targets: list[Path] = []
    for cells in rows:
        if len(cells) != len(header):
            errors.append(f"{index.relative_to(root).as_posix()}: 归档索引行列数不一致")
            continue
        document_links = _local_links(cells[document_index], index)
        if len(document_links) != 1:
            errors.append(f"{index.relative_to(root).as_posix()}: 归档文档入口必须是一个本地链接")
            continue
        target = document_links[0][1]
        targets.append(target)
        if (
            target == index
            or not target.is_file()
            or target.suffix.lower() != ".md"
            or not _is_within(target, area)
        ):
            errors.append(f"{index.relative_to(root).as_posix()}: 归档文档入口越界或不存在")

        current = cells[current_index].strip()
        if current == "无，仅保留历史证据":
            continue
        current_links = _local_links(current, index)
        if (
            len(current_links) != 1
            or not current_links[0][1].is_file()
            or current_links[0][1].suffix.lower() != ".md"
            or not _is_within(current_links[0][1], root)
            or _is_within(current_links[0][1], root / "archive")
        ):
            errors.append(
                f"{index.relative_to(root).as_posix()}: 当前承接真源必须指向活动 Markdown，"
                "或写“无，仅保留历史证据”"
            )

    counts = Counter(target.resolve(strict=False) for target in targets)
    for path in paths:
        if path == index or not _is_within(path, area):
            continue
        count = counts[path.resolve(strict=False)]
        if count != 1:
            errors.append(
                f"{path.relative_to(root).as_posix()}: 必须由归档索引登记一次，实际 {count} 次"
            )


def collect_doc_consistency(root: Path | None = None) -> tuple[list[str], list[str]]:
    workspace = (root or Path(__file__).resolve().parents[2]).resolve()
    errors: list[str] = []
    _check_required_files(workspace, errors)
    paths = _walk_markdown(workspace, workspace, exclude_archive=True)
    _check_markdown_files(workspace, paths, errors)
    _check_required_links(workspace, errors)
    items = _parse_backlog(workspace, errors)
    _check_plans(workspace, items, errors)
    _check_registry(workspace, errors)
    return errors, []


def collect_archive_consistency(root: Path | None = None) -> tuple[list[str], list[str]]:
    workspace = (root or Path(__file__).resolve().parents[2]).resolve()
    errors: list[str] = []
    paths = tuple(
        path
        for relative in ARCHIVE_AREAS
        for path in _walk_markdown(
            workspace,
            workspace / relative,
            exclude_archive=False,
        )
    )
    _check_markdown_files(workspace, paths, errors)
    for relative in ARCHIVE_AREAS:
        _check_archive_area(workspace, workspace / relative, paths, errors)
    return errors, []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-root", type=Path)
    parser.add_argument("--scope", choices=("active", "archive"), default="active")
    args = parser.parse_args()
    collector = collect_doc_consistency if args.scope == "active" else collect_archive_consistency
    errors, warnings = collector(args.workspace_root)
    for warning in warnings:
        print(f"[WARN] {warning}")
    if errors:
        for error in errors:
            print(f"[FAIL] {error}")
        print(f"FAILED: {len(errors)} issue(s)")
        return 1
    label = "活动文档机械一致性" if args.scope == "active" else "归档机械一致性"
    print(f"{label}检查通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
