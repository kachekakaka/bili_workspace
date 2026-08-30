# T-ARCHIVE 归档机械门禁

- Registry ID：`T-ARCHIVE`
- 执行类别：`affected_only`
- 触发条件：`archive/docs/**` 或 `archive/SoftwareTesting/**` 发生变化，活动方案关闭归档，或归档索引引用的当前 Markdown 被重命名/删除。
- 输入：两个完整归档区及索引引用的当前项目 Markdown；本项一旦被选择就检查完整归档区，不只检查变更行。
- fixture：与 T-DOC 共用标准库隔离正反夹具，不使用项目数据。
- 工作目录：仓库根目录。
- 环境条件：环境预置 `python`，仅使用 Python 标准库。

## 规范命令

```text
python -B -X utf8 SoftwareTesting/doc_consistency/test_doc_consistency.py --scope archive
```

规则资产本身变化时，先运行：

```text
python -B -X utf8 SoftwareTesting/doc_consistency/test_doc_consistency_rules.py
```

## 断言

每个归档区必须有 UTF-8、LF 的 `README.md` 索引表，并至少包含“归档文档”和“当前承接真源”列。每份归档 Markdown 必须由本区索引恰好登记一次；索引不得重复、越界或链接不存在的正文。当前承接真源只能是一个项目内活动 Markdown，或精确写“无，仅保留历史证据”。归档正文中的普通相对链接和标题锚点必须有效。

T-ARCHIVE 不固定索引列数或历史正文措辞，不判断历史事实是否仍然正确，也不把历史结果提升为当前状态。活动入口、方案关系和 Registry 由 T-DOC 承接。

## 结果与清理

结果语义遵守 [测试协议](../PROTOCOL.md)。本项只读，不创建测试运行目录、不启动产品，也不接触真实数据。
