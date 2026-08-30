# T-DOC 文档机械门禁

- Registry ID：`T-DOC`
- 执行类别：`full`
- 输入：当前工作区的活动 Markdown；扫描不进入 `archive/**`，并排除标准项目级 Skill 资产目录。
- fixture：标准库临时目录中的最小正反行为夹具，不使用项目数据。
- 工作目录：仓库根目录。
- 环境条件：Python 3.11，仅使用标准库。

## 规范命令

规则实现变化时先运行夹具：

```text
python -B -X utf8 SoftwareTesting/doc_consistency/test_doc_consistency_rules.py
```

随后运行当前项目门禁：

```text
python -B -X utf8 SoftwareTesting/doc_consistency/test_doc_consistency.py
```

## 稳定断言

T-DOC 只检查适合机械判定且低误报的关系：

- 活动 Markdown 使用 UTF-8 和 LF，普通本地链接及标题锚点有效；
- AGENTS、项目 README、文档入口、测试入口及两个文档门禁入口存在并互相接线；
- `待实施`、`实施中`待办有且只有一份由自身链接的活动方案，任一待办没有多份方案，方案保留三项验证声明；
- 测试 Registry 的 ID 合法且唯一，入口是有效本地链接，并保留 T-DOC 与 T-ARCHIVE。

门禁不固定目录拓扑、两跳可达性、导航数量、表格列数、正文措辞、历史版本、源码 Token 或实现文件清单；这些结构本身不是产品行为。归档正文和索引由 T-ARCHIVE 在受影响时检查。

## 结果与清理

结果语义遵守[测试协议](../PROTOCOL.md)。T-DOC 只读；规则夹具只使用并自动清理系统临时目录，不创建项目测试 run、不启动产品，也不接触真实数据。
