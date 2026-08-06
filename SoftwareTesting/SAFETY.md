# 测试安全

## 测试根与清理边界

默认仓库外测试根为：

```text
Windows：D:\Projects\python\bili_workspace_test
Linux/macOS：${TMPDIR:-/tmp}/bili_workspace_test
```

可以用 `BILI_TEST_ROOT` 覆盖默认根，但仍必须位于仓库外且不能包含仓库。测试入口首次创建根时写入 `.bili-workspace-test-root.json`；已有根缺少该标记、标记不属于当前仓库、目录是符号链接/重解析点，或测试根与仓库互相包含时必须停止。

每次运行只能使用该根下新建且直接相邻的 `<run-id>/`，并写入 `.bili-workspace-test-run.json`。配置、userdata、数据库、下载、运行时、媒体工具、HOME、缓存、临时文件、Python 字节码、pytest basetemp、日志和结果都必须位于该目录；最终状态写入 `results/result.json`，取值为 `passed`、`failed`、`blocked`、`inconclusive` 或 `not_run`。

测试输出默认保留。已确认方案明确列明清理、本任务创建且所有权可验证的精确 `<run-id>/` 时，重新验证所有权并展示精确绝对路径后，可随该方案的实施授权清理。方案未列明、使用宽泛匹配或未解析路径、其他运行、测试根、仓库外非任务产物、所有权不明或涉及真实数据的删除，仍须取得精确授权；不得删除项目目录。

## 真实数据与进程

- 禁止读取、修改或复制真实配置、数据库、Cookie、Token、媒体、账号资料和其他用户数据。
- 项目完整自检只同步启动本次命令直接拥有的 Python、BBDown、FFmpeg 和 Node 子进程，不启动应用服务、浏览器或容器。
- 只管理本次启动且记录了所有权的进程，禁止按进程名称批量结束。
- fixture、缓存、日志和输出必须位于隔离临时目录或已确认的运行目录，不能写入真实持久化目录。
- 需要真实网络、外部费用或特殊环境的项目必须登记为 `explicit`，并另行取得授权。

## 敏感信息

测试输入只使用虚构凭据和隔离数据。日志、失败输出和交接摘要不得回显秘密或原始运行现场。
