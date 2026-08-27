# 文档机械门禁

- Registry ID：`T-DOC`
- 执行类别：`full`
- 触发条件：本仓库的活动文档骨架、入口、链接、生命周期或 Registry 发生变化；全量测试时始终执行。归档正文和索引行完整性由 `T-ARCHIVE` 承接。
- 输入：当前工作区的活动 Markdown 和固定入口；活动扫描不进入 `archive/**`，并精确排除任意层级标准项目级 Skill 根中的
  工具资产，不排除相邻工具目录内容或其他位置的 `SKILL.md`。
- fixture：门禁资产自测试使用脚本内置的隔离正反夹具，不使用项目数据。
- 工作目录：仓库根目录。
- 环境条件：环境预置 `python`，仅使用 Python 标准库。

## 规范命令

安装或更新门禁资产时先运行规则夹具：

```text
python -B -X utf8 SoftwareTesting/doc_consistency/test_doc_consistency_rules.py
```

随后运行当前项目的 `T-DOC`：

```text
python -B -X utf8 SoftwareTesting/doc_consistency/test_doc_consistency.py
```

## 断言

门禁机械检查固定路径与大小写、活动 Markdown 的 UTF-8 与 LF、普通相对链接和标题锚点、必要入口、两跳可达性、待办与方案生命周期及四列测试 Registry。标准根和已排除路径之外，含活动 Markdown 的顶层目录必须由根 README、项目文档入口或测试总入口直接链接目录内的 Markdown 所有者入口。任意层级的 `.agents/skills/**`、`.cursor/skills/**`、`.claude/skills/**`、`.codex/skills/**`、`.opencode/skills/**`、`.opencode/skill/**` 和 `.github/skills/**` 不接受这些通用 Markdown 检查；相邻工具目录内容和其他位置的 `SKILL.md` 仍按原规则检查。`待确认` 待办可以没有方案或链接一份草案，`待实施` 与 `实施中` 待办必须链接一份方案，`暂缓` 不得保留活动方案；任一待办最多一份。根 README 与 `docs/README.md` 直接链接至少三份相同专题 Markdown 时给出重复导航 warning。它只要求归档索引入口存在并禁止活动导航直链归档正文，不读取归档索引行或正文；也不判断正文事实、生命周期语义、测试设计质量或 Skill 正文质量。

本仓库内脚本是本项目门禁执行真源。外部骨架 Skill 只可作为另一个任务的升级输入；同步必须审查行为差异，不以文件哈希相等覆盖项目内性能和范围适配。

## 结果语义

- `passed`：当前要求执行的命令均以退出码 0 完成。
- `failed`：命令已进入可判定阶段，并报告机械不一致或夹具断言失败。
- `blocked`：`python` 或必要的只读文件不可用，命令未进入可判定阶段。
- `inconclusive`：命令被中断或运行器内部异常，输出不足以判断一致性。
- `not_run`：命令没有执行；静态检查或其他替代证据不能把本项改写为 `passed`。

结果只绑定命令执行时的工作区。待办退出或空条件目录清理会形成新的活动候选；方案归档和索引更新还会触发 `T-ARCHIVE`。生命周期关闭后必须对最终状态重新运行适用门禁，施工中途结果不能替代最终状态结论。

## 清理

`T-DOC` 只读。规则夹具只使用并自动清理系统临时目录；两个命令都不创建项目测试根或产品进程，也不接触真实数据。
