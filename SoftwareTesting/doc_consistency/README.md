# T-DOC 文档机械门禁

- Registry ID：`T-DOC`
- 执行类别：`full`
- 工作目录：仓库根目录
- 输入：当前工作树中的活动 Markdown、归档索引和骨架入口；精确排除项目级 Agent Skill 工具资产和生成运行时 `.runtime`
- 唯一职责：检查固定文件、导航、相对链接、标题锚点、两跳可达性、待办与方案生命周期、测试 Registry、归档登记，以及全部活动 Markdown 只能通过归档索引进入历史材料

规则夹具命令：

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m unittest discover -s SoftwareTesting\doc_consistency -p "test_doc_consistency_rules.py"
```

目标项目命令：

```powershell
.\.venv\Scripts\python.exe -B -X utf8 SoftwareTesting\doc_consistency\test_doc_consistency.py --workspace-root .
```

缺少 Python 或无法读取工作树时为 `blocked`；门禁报告机械错误时为 `failed`；运行器中断或异常导致证据不可解释时为 `inconclusive`。命令只读项目内容，规则夹具仅创建并自动清理系统临时目录。
