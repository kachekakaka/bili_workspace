# 文档机械门禁

- Registry ID：`T-DOC`
- 执行类别：`full`
- 触发条件：本仓库或采用标准骨架的目标项目，其文档骨架、入口、链接、生命周期、Registry 或归档结构发生变化；全量测试时始终执行。
- 输入：当前标准骨架工作区的活动 Markdown、归档索引和固定路径；精确排除任意层级标准项目级 Skill 根中的
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

门禁机械检查标准骨架的固定路径与大小写、UTF-8 与 LF、普通相对链接和标题锚点、必要入口、两跳可达性、待办与方案生命周期、四列测试 Registry 及归档登记。标准根、归档和已排除路径之外，含活动 Markdown 的顶层目录必须由根 README、项目文档入口或测试总入口直接链接目录内的 Markdown 所有者入口。任意层级的 `.agents/skills/**`、`.cursor/skills/**`、`.claude/skills/**`、`.codex/skills/**`、`.opencode/skills/**`、`.opencode/skill/**` 和 `.github/skills/**` 不接受这些通用 Markdown 检查；相邻工具目录内容和其他位置的 `SKILL.md` 仍按原规则检查。`待确认` 待办可以没有方案或链接一份方案，`实施中` 待办必须链接一份方案，其他活动状态不得保留方案；任一待办最多一份。根 README 与 `docs/README.md` 直接链接至少三份相同专题 Markdown 时给出重复导航 warning。它不解析工具配置或自定义 Skill 根，也不判断正文事实、生命周期语义、测试设计质量、Skill 正文质量或非标准成熟项目是否结构等价。

## 结果语义

- `passed`：当前要求执行的命令均以退出码 0 完成。
- `failed`：命令已进入可判定阶段，并报告机械不一致或夹具断言失败。
- `blocked`：`python` 或必要的只读文件不可用，命令未进入可判定阶段。
- `inconclusive`：命令被中断或运行器内部异常，输出不足以判断一致性。
- `not_run`：命令没有执行；静态检查或其他替代证据不能把本项改写为 `passed`。

结果只绑定命令执行时的工作区。待办退出、方案归档、索引更新或空条件目录清理会形成新候选；生命周期关闭后
必须对最终状态重新运行本门禁，施工中途结果不能替代最终状态结论。

## 清理

`T-DOC` 只读。规则夹具只使用并自动清理系统临时目录；两个命令都不创建项目测试根或产品进程，也不接触真实数据。
