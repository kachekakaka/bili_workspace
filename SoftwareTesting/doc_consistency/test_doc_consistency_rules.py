#!/usr/bin/env python3
"""文档机械门禁的最小行为夹具。"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_doc_consistency import collect_archive_consistency, collect_doc_consistency


SCRIPT = Path(__file__).with_name("test_doc_consistency.py")
BASE_FILES = {
    "AGENTS.md": """\
# 项目协作约束

- [构建与交付](README.md#构建与交付)
- [项目文档](docs/README.md)
- [测试治理](SoftwareTesting/README.md)
""",
    "README.md": """\
# 示例项目

- [项目文档](docs/README.md)
- [测试治理](SoftwareTesting/README.md)

## 构建与交付

本夹具没有交付产物。
""",
    "docs/README.md": """\
# 项目文档

- [待办](已知问题与待做需求.md)
- [测试](软件测试.md)
""",
    "docs/已知问题与待做需求.md": """\
# 已知问题与待做需求

## FEATURE-001：示例能力

- 状态：待确认
""",
    "docs/软件测试.md": """\
# 软件测试

| ID | 执行类别 | 入口 | 唯一职责 |
| --- | --- | --- | --- |
| T-DOC | full | [文档门禁](../SoftwareTesting/doc_consistency/README.md) | 活动文档 |
| T-ARCHIVE | affected_only | [归档门禁](../SoftwareTesting/archive_consistency/README.md) | 归档文档 |
""",
    "SoftwareTesting/README.md": """\
# 测试治理

- [Registry](../docs/软件测试.md)
- [文档门禁](doc_consistency/README.md)
- [归档门禁](archive_consistency/README.md)
""",
    "SoftwareTesting/doc_consistency/README.md": "# 文档门禁\n",
    "SoftwareTesting/archive_consistency/README.md": "# 归档门禁\n",
    "archive/docs/README.md": """\
# 文档归档

| 归档文档 | 当前承接真源 |
| --- | --- |
""",
    "archive/SoftwareTesting/README.md": """\
# 测试归档

| 归档文档 | 当前承接真源 |
| --- | --- |
""",
}


class DocConsistencyRulesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        for relative, content in BASE_FILES.items():
            self.write(relative, content)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write(self, relative: str, content: str) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
        return path

    def read(self, relative: str) -> str:
        return (self.root / relative).read_text(encoding="utf-8")

    def replace(self, relative: str, old: str, new: str) -> None:
        content = self.read(relative)
        self.assertIn(old, content)
        self.write(relative, content.replace(old, new))

    def issues(self) -> list[str]:
        errors, warnings = collect_doc_consistency(self.root)
        self.assertEqual([], warnings)
        return errors

    def archive_issues(self) -> list[str]:
        errors, warnings = collect_archive_consistency(self.root)
        self.assertEqual([], warnings)
        return errors

    def assert_has(self, issues: list[str], expected: str) -> None:
        self.assertTrue(
            any(expected in issue for issue in issues),
            f"未发现包含 {expected!r} 的问题：{issues}",
        )

    def assert_clean(self) -> None:
        self.assertEqual([], self.issues())

    def add_plan(self, status: str = "实施中") -> None:
        self.write(
            "docs/已知问题与待做需求.md",
            f"""\
# 已知问题与待做需求

## FEATURE-001：示例能力

- 状态：{status}
- 方案：[实施方案](方案/FEATURE-001-示例能力.md)
""",
        )
        self.write(
            "docs/方案/FEATURE-001-示例能力.md",
            """\
# 示例能力方案

- 测试层级：普通验证
- 验证影响域：示例能力
- 具体验证项：运行行为测试
""",
        )

    def add_archive(self) -> None:
        self.write("archive/docs/旧设计.md", "# 旧设计\n")
        self.write(
            "archive/docs/README.md",
            """\
# 文档归档

| 归档文档 | 历史职责 | 当前承接真源 |
| --- | --- | --- |
| [旧设计](旧设计.md) | 旧说明 | [当前入口](../../docs/README.md) |
""",
        )

    def test_minimal_fixture_passes(self) -> None:
        self.assert_clean()
        self.assertEqual([], self.archive_issues())

    def test_required_files_and_navigation_are_enforced(self) -> None:
        (self.root / "docs" / "软件测试.md").unlink()
        self.replace("AGENTS.md", "- [项目文档](docs/README.md)\n", "")

        errors = self.issues()

        self.assert_has(errors, "docs/软件测试.md: 缺少必要入口文件")
        self.assert_has(errors, "AGENTS.md: 缺少必要入口 docs/README.md")

    def test_optional_context_requires_agents_entry(self) -> None:
        self.write("CONTEXT.md", "# 领域语言\n")
        self.assert_has(self.issues(), "AGENTS.md: 缺少必要入口 CONTEXT.md")

        self.write("AGENTS.md", self.read("AGENTS.md") + "- [领域语言](CONTEXT.md)\n")
        self.assert_clean()

    def test_utf8_lf_links_and_anchors_are_checked(self) -> None:
        (self.root / "docs" / "notes.md").write_bytes(b"# Notes\r\n")
        (self.root / "docs" / "broken.md").write_bytes(b"\xff\xfe")
        self.write(
            "docs/extra.md",
            "# Extra\n\n[missing](missing.md)\n[anchor](README.md#missing)\n",
        )

        errors = self.issues()

        self.assert_has(errors, "docs/notes.md: Markdown 必须使用 LF")
        self.assert_has(errors, "docs/broken.md: Markdown 必须是有效 UTF-8")
        self.assert_has(errors, "docs/extra.md: 链接目标不存在: missing.md")
        self.assert_has(errors, "docs/extra.md: 标题锚点不存在: README.md#missing")

    def test_fenced_examples_and_project_skills_are_ignored(self) -> None:
        self.write(
            "docs/example.md",
            "# Example\n\n```markdown\n[missing](missing.md)\n```\n",
        )
        self.write(
            ".codex/skills/example/SKILL.md",
            "# Skill\r\n\r\n[missing](missing.md)\r\n",
        )
        self.assert_clean()

        self.write(".codex/notes.md", "# Notes\n\n[missing](missing.md)\n")
        self.assert_has(self.issues(), ".codex/notes.md: 链接目标不存在")

    def test_ready_or_implementing_item_requires_one_linked_plan(self) -> None:
        self.replace("docs/已知问题与待做需求.md", "待确认", "待实施")
        self.assert_has(
            self.issues(),
            "待实施待办 FEATURE-001 必须有且只有一份活动方案",
        )

        self.add_plan()
        self.assert_clean()

    def test_plan_must_belong_to_its_item_and_keep_validation_fields(self) -> None:
        self.add_plan()
        self.replace(
            "docs/已知问题与待做需求.md",
            "- 方案：[实施方案](方案/FEATURE-001-示例能力.md)\n",
            "",
        )
        self.replace(
            "docs/方案/FEATURE-001-示例能力.md",
            "- 具体验证项：运行行为测试\n",
            "",
        )

        errors = self.issues()

        self.assert_has(errors, "必须由对应待办条目链接")
        self.assert_has(errors, "具体验证项 必须且只能出现一次")

    def test_one_item_cannot_keep_multiple_plans_and_paused_plan(self) -> None:
        self.add_plan("暂缓")
        self.write(
            "docs/方案/FEATURE-001-备选.md",
            """\
# 备选

- 测试层级：普通验证
- 验证影响域：示例
- 具体验证项：行为测试
""",
        )
        self.write(
            "docs/已知问题与待做需求.md",
            self.read("docs/已知问题与待做需求.md")
            + "- 备选：[方案](方案/FEATURE-001-备选.md)\n",
        )

        errors = self.issues()

        self.assert_has(errors, "待办 FEATURE-001 存在多份活动方案")
        self.assert_has(errors, "暂缓待办 FEATURE-001 不得保留活动方案")

    def test_backlog_status_and_id_uniqueness_are_enforced(self) -> None:
        self.write(
            "docs/已知问题与待做需求.md",
            """\
# 已知问题与待做需求

## FEATURE-001：第一项

- 状态：未知

## FEATURE-001：第二项

- 说明：缺少状态
""",
        )

        errors = self.issues()

        self.assert_has(errors, "FEATURE-001 使用非法状态: 未知")
        self.assert_has(errors, "待办 ID 重复: FEATURE-001")

    def test_registry_schema_is_flexible_but_ids_and_entries_are_checked(self) -> None:
        self.write(
            "docs/软件测试.md",
            """\
# 软件测试

| 说明 | 入口 | ID |
| --- | --- | --- |
| 活动文档 | [文档门禁](../SoftwareTesting/doc_consistency/README.md) | T-DOC |
| 归档文档 | [归档门禁](../SoftwareTesting/archive_consistency/README.md) | T-ARCHIVE |
""",
        )
        self.assert_clean()

        self.write(
            "docs/软件测试.md",
            self.read("docs/软件测试.md")
            + "| 重复 | [文档门禁](../SoftwareTesting/doc_consistency/README.md) | T-DOC |\n",
        )
        self.assert_has(self.issues(), "测试项 ID 重复: T-DOC")

    def test_registry_requires_core_gate_entries(self) -> None:
        self.replace(
            "docs/软件测试.md",
            "| T-ARCHIVE | affected_only | [归档门禁](../SoftwareTesting/archive_consistency/README.md) | 归档文档 |\n",
            "",
        )
        self.assert_has(self.issues(), "Registry 缺少必需测试项 T-ARCHIVE")

    def test_archive_index_owns_each_document_once(self) -> None:
        self.write("archive/docs/旧设计.md", "# 旧设计\n")
        self.assert_has(self.archive_issues(), "必须由归档索引登记一次，实际 0 次")

        self.add_archive()
        self.assertEqual([], self.archive_issues())

        self.write(
            "archive/docs/README.md",
            self.read("archive/docs/README.md")
            + "| [重复](旧设计.md) | 重复 | 无，仅保留历史证据 |\n",
        )
        self.assert_has(self.archive_issues(), "必须由归档索引登记一次，实际 2 次")

    def test_archive_current_source_must_be_active(self) -> None:
        self.add_archive()
        self.replace(
            "archive/docs/README.md",
            "[当前入口](../../docs/README.md)",
            "[错误承接](旧设计.md)",
        )
        self.assert_has(self.archive_issues(), "当前承接真源必须指向活动 Markdown")

    def test_active_scope_does_not_read_archive_body(self) -> None:
        self.write("archive/docs/未登记.md", "# 历史\n\n[missing](missing.md)\n")
        self.assert_clean()
        self.assert_has(self.archive_issues(), "archive/docs/未登记.md: 链接目标不存在")

    def test_cli_exit_code_matches_result(self) -> None:
        passed = subprocess.run(
            [sys.executable, "-B", "-X", "utf8", str(SCRIPT), "--workspace-root", str(self.root)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, passed.returncode, passed.stdout + passed.stderr)

        (self.root / "AGENTS.md").unlink()
        failed = subprocess.run(
            [sys.executable, "-B", "-X", "utf8", str(SCRIPT), "--workspace-root", str(self.root)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(1, failed.returncode, failed.stdout + failed.stderr)
        self.assertIn("[FAIL]", failed.stdout)


if __name__ == "__main__":
    unittest.main()
