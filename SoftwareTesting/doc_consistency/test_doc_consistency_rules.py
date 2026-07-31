#!/usr/bin/env python3
"""文档机械一致性检查器的隔离正反夹具。"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_doc_consistency import collect_doc_consistency


SCRIPT = Path(__file__).with_name("test_doc_consistency.py")

BASE_FILES = {
    "AGENTS.md": """\
# 项目协作约束

- [构建与交付](README.md#构建与交付)
- [文档入口](docs/README.md)
- [测试入口](SoftwareTesting/README.md)
""",
    "README.md": """\
# 示例项目

- [项目文档](docs/README.md)
- [测试入口](SoftwareTesting/README.md)

## 构建与交付

本夹具没有产品构建和交付产物，均不适用。
""",
    "docs/README.md": """\
# 文档入口

- [需求文档](需求文档.md)
- [设计文档](设计文档.md)
- [已知问题与待做需求](已知问题与待做需求.md)
- [软件测试](软件测试.md)
- [文档归档](../archive/docs/README.md)
""",
    "docs/需求文档.md": """\
# 需求文档

当前没有已交付的产品行为。
""",
    "docs/设计文档.md": """\
# 设计文档

当前没有产品实现。
""",
    "docs/已知问题与待做需求.md": """\
# 已知问题与待做需求

## FEATURE-001：示例能力

- 状态：待实施
""",
    "docs/软件测试.md": """\
# 软件测试

| ID | 执行类别 | 入口 | 唯一职责 |
| --- | --- | --- | --- |
| T-DOC | full | [文档一致性](../SoftwareTesting/doc_consistency/README.md) | 检查文档骨架与入口 |
""",
    "SoftwareTesting/README.md": """\
# 测试入口

- [通用协议](PROTOCOL.md)
- [安全约束](SAFETY.md)
- [活动测试项 Registry](../docs/软件测试.md)
- [文档一致性](doc_consistency/README.md)
""",
    "SoftwareTesting/PROTOCOL.md": """\
# 测试协议

普通验证为默认层级；全量测试和正式认证仅在明确选择后执行。
""",
    "SoftwareTesting/SAFETY.md": """\
# 测试安全

示例项目不涉及真实数据或产品进程，相关规则不适用。
""",
    "SoftwareTesting/doc_consistency/README.md": """\
# 文档一致性

该测试项机械检查长期文档骨架。
""",
    "archive/docs/README.md": """\
# 文档归档

| 归档文档 | 历史职责 | 当前承接真源 |
| --- | --- | --- |
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

    def issues(self) -> tuple[list[str], list[str]]:
        return collect_doc_consistency(self.root)

    def assert_has(self, issues: list[str], expected: str) -> None:
        self.assertTrue(
            any(expected in issue for issue in issues),
            f"未发现包含 {expected!r} 的问题：{issues}",
        )

    def assert_clean(self) -> None:
        errors, warnings = self.issues()
        self.assertEqual([], errors)
        self.assertEqual([], warnings)

    def add_valid_plan(self) -> None:
        self.write(
            "docs/已知问题与待做需求.md",
            """\
# 已知问题与待做需求

## FEATURE-001：示例能力

- 状态：实施中
- [活动方案](方案/FEATURE-001-示例能力.md)
""",
        )
        self.write(
            "docs/方案/FEATURE-001-示例能力.md",
            """\
# 示例能力方案

- 测试层级：普通验证
- 验证影响域：文档骨架
- 具体验证项：运行 T-DOC
""",
        )

    def add_valid_suite(self) -> None:
        self.write(
            "SoftwareTesting/api/README.md",
            "# API 测试\n\n只定义该测试项的机械入口。\n",
        )
        self.write(
            "SoftwareTesting/README.md",
            self.read("SoftwareTesting/README.md")
            + "- [API 测试](api/README.md)\n",
        )
        self.write(
            "docs/软件测试.md",
            self.read("docs/软件测试.md")
            + "| T-API | affected_only | [API 测试](../SoftwareTesting/api/README.md) | 检查 API 测试入口 |\n",
        )

    def add_valid_archive(self) -> None:
        self.write("archive/docs/旧设计.md", "# 旧设计\n")
        self.write(
            "archive/docs/README.md",
            """\
# 文档归档

| 归档文档 | 历史职责 | 当前承接真源 |
| --- | --- | --- |
| [旧设计](旧设计.md) | 旧实现说明 | [当前设计](../../docs/设计文档.md) |
""",
        )

    def test_minimal_fixture_passes(self) -> None:
        self.assert_clean()

    def test_required_file_and_exact_case_are_enforced(self) -> None:
        (self.root / "docs" / "需求文档.md").unlink()
        (self.root / "AGENTS.md").rename(self.root / "agents.md")

        errors, _ = self.issues()

        self.assert_has(errors, "AGENTS.md: 缺少名称与大小写完全匹配的必需文件")
        self.assert_has(errors, "docs/需求文档.md: 缺少名称与大小写完全匹配的必需文件")

    def test_context_is_optional_but_single_root_context_requires_entry(self) -> None:
        self.assert_clean()

        self.write("CONTEXT.md", "# 项目概念\n")
        errors, _ = self.issues()
        self.assert_has(errors, "AGENTS.md: 缺少必要入口 CONTEXT.md")

        self.write(
            "AGENTS.md",
            self.read("AGENTS.md") + "- [项目概念](CONTEXT.md)\n",
        )
        self.assert_clean()

    def test_context_map_and_nested_context_are_rejected(self) -> None:
        self.write("CONTEXT-MAP.md", "# 多上下文映射\n")
        self.write("docs/子域/CONTEXT.md", "# 子域上下文\n")

        errors, _ = self.issues()

        self.assert_has(errors, "CONTEXT-MAP.md: 本骨架只支持单一上下文项目")
        self.assert_has(errors, "docs/子域/CONTEXT.md: 本骨架不允许嵌套 CONTEXT.md")

    def test_active_markdown_requires_utf8_and_lf(self) -> None:
        (self.root / "docs" / "需求文档.md").write_bytes(b"# title\r\n")
        (self.root / "docs" / "设计文档.md").write_bytes(b"\xff\xfe\x00")

        errors, _ = self.issues()

        self.assert_has(errors, "docs/需求文档.md: 活动 Markdown 和归档索引必须使用 LF")
        self.assert_has(errors, "docs/设计文档.md: 必须是有效 UTF-8")

    def test_local_link_and_heading_anchor_are_checked(self) -> None:
        self.write(
            "docs/需求文档.md",
            """\
# 需求文档

- [不存在](不存在.md)
- [错误锚点](设计文档.md#不存在)
""",
        )

        errors, _ = self.issues()

        self.assert_has(errors, "docs/需求文档.md: 链接目标不存在: 不存在.md")
        self.assert_has(errors, "docs/需求文档.md: 标题锚点不存在: 设计文档.md#不存在")

    def test_fenced_example_is_not_treated_as_link_or_machine_syntax(self) -> None:
        self.write(
            "docs/设计文档.md",
            self.read("docs/设计文档.md")
            + """\

```markdown
[仅作示例](不存在.md)
[引用式示例][ref]
C:\\Users\\example\\project
```
""",
        )

        self.assert_clean()

    def test_required_navigation_is_enforced(self) -> None:
        self.replace("AGENTS.md", "- [文档入口](docs/README.md)\n", "")
        self.replace("README.md", "- [测试入口](SoftwareTesting/README.md)\n", "")
        self.replace("docs/README.md", "- [需求文档](需求文档.md)\n", "")
        self.replace(
            "SoftwareTesting/README.md",
            "- [安全约束](SAFETY.md)\n",
            "",
        )

        errors, _ = self.issues()

        self.assert_has(errors, "AGENTS.md: 缺少必要入口 docs/README.md")
        self.assert_has(errors, "README.md: 缺少必要入口 SoftwareTesting/README.md")
        self.assert_has(errors, "docs/README.md: 缺少必要入口 docs/需求文档.md")
        self.assert_has(
            errors,
            "SoftwareTesting/README.md: 缺少必要入口 SoftwareTesting/SAFETY.md",
        )

    def test_root_readme_must_not_link_back_to_agents(self) -> None:
        self.write(
            "README.md",
            self.read("README.md") + "- [协作规则](AGENTS.md)\n",
        )

        errors, _ = self.issues()

        self.assert_has(
            errors,
            "README.md: 不得反向链接 AGENTS.md；AGENTS.md 是协作第一入口",
        )

    def test_docs_two_link_reachability_passes(self) -> None:
        self.write(
            "docs/README.md",
            self.read("docs/README.md") + "- [运维文档](运维/README.md)\n",
        )
        self.write(
            "docs/运维/README.md",
            "# 运维文档\n\n- [值班说明](值班说明.md)\n",
        )
        self.write("docs/运维/值班说明.md", "# 值班说明\n")

        self.assert_clean()

    def test_docs_third_link_is_rejected(self) -> None:
        self.write(
            "docs/README.md",
            self.read("docs/README.md") + "- [第一层](第一层.md)\n",
        )
        self.write("docs/第一层.md", "# 第一层\n\n- [第二层](第二层.md)\n")
        self.write("docs/第二层.md", "# 第二层\n\n- [第三层](第三层.md)\n")
        self.write("docs/第三层.md", "# 第三层\n")

        errors, _ = self.issues()

        self.assert_has(
            errors,
            "docs/第三层.md: 活动文档不能从 docs/README.md 通过两次实际 Markdown 链接到达",
        )

    def test_suite_readme_requires_direct_navigation_and_registry_entry(self) -> None:
        self.add_valid_suite()
        self.assert_clean()

        self.replace(
            "SoftwareTesting/README.md",
            "- [API 测试](api/README.md)\n",
            "",
        )
        errors, _ = self.issues()
        self.assert_has(
            errors,
            "SoftwareTesting/api/README.md: 活动 suite README 必须从 SoftwareTesting/README.md 直接链接",
        )

        self.write(
            "SoftwareTesting/README.md",
            self.read("SoftwareTesting/README.md")
            + "- [API 测试](api/README.md)\n",
        )
        self.replace(
            "docs/软件测试.md",
            "| T-API | affected_only | [API 测试](../SoftwareTesting/api/README.md) | 检查 API 测试入口 |\n",
            "",
        )
        errors, _ = self.issues()
        self.assert_has(
            errors,
            "SoftwareTesting/api/README.md: 活动 suite README 必须由 Registry 测试项链接",
        )

    def test_backlog_h2_id_status_and_uniqueness_are_enforced(self) -> None:
        self.write(
            "docs/已知问题与待做需求.md",
            """\
# 已知问题与待做需求

## 普通标题

## FEATURE-001：第一项

- 状态：未知

## FEATURE-001：第二项

- 说明：没有状态
""",
        )

        errors, _ = self.issues()

        self.assert_has(errors, "所有二级标题必须使用“待办ID：标题”格式")
        self.assert_has(errors, "待办 ID 重复: FEATURE-001")
        self.assert_has(errors, "FEATURE-001 使用非法状态: 未知")
        self.assert_has(errors, "FEATURE-001 必须且只能有一个状态")

    def test_valid_implementing_item_has_one_linked_complete_plan(self) -> None:
        self.add_valid_plan()
        self.assert_clean()

    def test_plan_lifecycle_link_and_fields_are_enforced(self) -> None:
        self.replace("docs/已知问题与待做需求.md", "待实施", "实施中")
        errors, _ = self.issues()
        self.assert_has(errors, "实施中待办 FEATURE-001 必须有且只有一份活动方案")

        self.add_valid_plan()
        self.replace(
            "docs/方案/FEATURE-001-示例能力.md",
            "- 具体验证项：运行 T-DOC\n",
            "",
        )
        errors, _ = self.issues()
        self.assert_has(errors, "具体验证项 必须且只能出现一次")

        self.replace(
            "docs/已知问题与待做需求.md",
            "- [活动方案](方案/FEATURE-001-示例能力.md)\n",
            "",
        )
        errors, _ = self.issues()
        self.assert_has(errors, "必须由对应待办条目实际链接")

    def test_non_implementing_item_must_not_have_active_plan(self) -> None:
        self.add_valid_plan()
        self.replace("docs/已知问题与待做需求.md", "实施中", "待实施")

        errors, _ = self.issues()

        self.assert_has(errors, "对应待办 FEATURE-001 不是“实施中”")
        self.assert_has(errors, "非实施中待办 FEATURE-001 不得有活动方案")

    def test_registry_requires_valid_unique_ids_categories_and_t_doc(self) -> None:
        self.write(
            "docs/软件测试.md",
            """\
# 软件测试

| ID | 执行类别 | 入口 | 唯一职责 |
| --- | --- | --- | --- |
| T-DOC | affected_only | [错误入口](../SoftwareTesting/README.md) | 错误示例 |
| T-DOC | sometimes | [重复入口](../SoftwareTesting/doc_consistency/README.md) | 重复示例 |
| invalid | full | [非法 ID](../SoftwareTesting/doc_consistency/README.md) | 非法示例 |
""",
        )

        errors, _ = self.issues()

        self.assert_has(errors, "测试项 ID 重复: T-DOC")
        self.assert_has(errors, "非法执行类别: sometimes")
        self.assert_has(errors, "非法测试项 ID: invalid")
        self.assert_has(errors, "T-DOC 的执行类别必须是 full")
        self.assert_has(
            errors,
            "T-DOC 必须指向 SoftwareTesting/doc_consistency/README.md",
        )

    def test_archive_document_requires_one_valid_index_entry(self) -> None:
        self.write("archive/docs/旧设计.md", "# 旧设计\n")
        errors, _ = self.issues()
        self.assert_has(errors, "archive/docs/旧设计.md: 必须由归档索引恰好登记一次，实际 0")

        self.add_valid_archive()
        self.assert_clean()

        self.write(
            "archive/docs/README.md",
            self.read("archive/docs/README.md")
            + "| [旧设计副本](旧设计.md) | 重复记录 | 无，仅保留历史证据 |\n",
        )
        errors, _ = self.issues()
        self.assert_has(errors, "archive/docs/旧设计.md: 归档索引重复登记 2 次")

    def test_archive_current_source_must_be_active_project_markdown(self) -> None:
        self.write("archive/docs/旧设计.md", "# 旧设计\n")
        self.write(
            "archive/docs/README.md",
            """\
# 文档归档

| 归档文档 | 历史职责 | 当前承接真源 |
| --- | --- | --- |
| [旧设计](旧设计.md) | 旧实现说明 | [另一份归档](旧设计.md) |
""",
        )

        errors, _ = self.issues()

        self.assert_has(
            errors,
            "当前承接真源必须链接一个项目内活动 Markdown",
        )

    def test_active_navigation_may_link_archive_index_but_not_body(self) -> None:
        self.add_valid_archive()
        self.assert_clean()

        self.write(
            "AGENTS.md",
            self.read("AGENTS.md") + "- [旧设计](archive/docs/旧设计.md)\n",
        )
        errors, _ = self.issues()
        self.assert_has(errors, "AGENTS.md: 活动导航不得直接链接归档正文")

    def test_machine_only_syntax_and_absolute_paths_are_warnings(self) -> None:
        self.write(
            "AGENTS.md",
            self.read("AGENTS.md")
            + """\
- [引用式入口][docs-ref]

[docs-ref]: docs/README.md
""",
        )
        self.write(
            "docs/软件测试.md",
            self.read("docs/软件测试.md")
            + "\n| 仅作说明 \\| 不属于 Registry |\n",
        )
        self.write(
            "docs/设计文档.md",
            self.read("docs/设计文档.md")
            + "\n本地示例：C:\\Users\\example\\project\n",
        )

        errors, warnings = self.issues()

        self.assertEqual([], errors)
        self.assert_has(warnings, "机器入口使用引用式链接")
        self.assert_has(warnings, "机器表格包含转义竖线")
        self.assert_has(warnings, "发现绝对本地用户路径")

    def test_content_semantics_are_outside_skeleton_scope(self) -> None:
        secret_like = "ghp_" + "0123456789abcdefghijklmnopqrstuvwxyz"
        self.write(
            "docs/设计文档.md",
            self.read("docs/设计文档.md")
            + f"""\

候选日期：2026-07-30
构建哈希：deadbeef
测试结果：暂未确认
示例 token：{secret_like}
## 实施方案

这里的内容真假应交给内容审计，不由骨架检查器判断。
""",
        )

        self.assert_clean()

    def test_cli_exit_code_matches_result(self) -> None:
        passed = subprocess.run(
            [
                sys.executable,
                "-B",
                "-X",
                "utf8",
                str(SCRIPT),
                "--workspace-root",
                str(self.root),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, passed.returncode, passed.stdout + passed.stderr)

        (self.root / "docs" / "需求文档.md").unlink()
        failed = subprocess.run(
            [
                sys.executable,
                "-B",
                "-X",
                "utf8",
                str(SCRIPT),
                "--workspace-root",
                str(self.root),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(1, failed.returncode, failed.stdout + failed.stderr)
        self.assertIn("[FAIL]", failed.stdout)


if __name__ == "__main__":
    unittest.main()
