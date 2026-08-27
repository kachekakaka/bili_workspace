# 测试安全

## 测试根与清理边界

默认仓库外测试根为：

```text
Windows：D:\Projects\python\bili_workspace_test
Linux/macOS：${TMPDIR:-/tmp}/bili_workspace_test
```

可以用 `BILI_TEST_ROOT` 覆盖默认根，但仍必须位于仓库外且不能包含仓库。测试入口首次创建根时写入 `.bili-workspace-test-root.json`；已有根缺少该标记、标记不属于当前仓库、目录是符号链接/重解析点，或测试根与仓库互相包含时必须停止。

每次运行只能使用该根下新建且直接相邻的 `<run-id>/`，并写入 `.bili-workspace-test-run.json`。同一测试根可以保存多个 Registry 测试项，但每个运行目录只能绑定一个 `test_id`，运行标记与结果身份必须一致，禁止让不同测试项共享同一 run-id。配置、userdata、数据库、下载、运行时、媒体工具、HOME、缓存、临时文件、Python 字节码、pytest basetemp、日志和结果都必须位于该目录；最终状态写入 `results/result.json`，取值为 `passed`、`failed`、`blocked`、`inconclusive` 或 `not_run`。

测试输出不会随普通测试或任务收尾自动删除，但所有原始运行证据都有期限。具有终态证明的 `passed`、`not_run` 在最终结果更新时间达到 72 小时后可成为普通 GC 候选；`failed`、`blocked`、`inconclusive` 在达到 7 天后可成为普通候选。方案或长期文档引用不延长期限，需要长期承接时只保存命令、候选身份、结果和必要结论。

新运行创建时结果必须明确为未终结，最终记录写入 `finalized_at`。既有或异常运行缺少终态证明时，达到 7 天后只能作为 `legacy_or_abandoned` 候选；该分类必须显式说明歧义并由用户对精确清单另行确认，不得混入普通候选或永久保护。

`tools/t_project_isolation.py gc-plan` 是只读规划，只读取测试根直接子目录的根标记、运行标记和结果，输出精确 run-id、分类、身份哈希与计划摘要，不递归统计内容。`gc-apply` 必须接收相同的逐项 run-id、分类和预期摘要，删除前重新构建计划；身份、状态、期限、摘要或路径边界发生任何漂移时整体拒绝。

只读规划使用 `python -B -X utf8 tools/t_project_isolation.py gc-plan --workspace-root .`；实际应用必须逐项传入 dry-run 展示的 `--candidate <run-id>:<category>`，并传入同一输出中的 `--expected-digest`。命令可用 `--test-root` 指定已存在测试根；缺失测试根时规划直接拒绝，不得因 dry-run 创建目录。

GC 只接受测试根的直接子目录和逐项完整 run-id，不接受前缀、glob、未知 schema、重解析点、测试根或项目目录。已确认方案明确列明清理、本任务创建且所有权可验证的精确 `<run-id>/` 时，可按方案授权处理；其他仓库外运行仍须先展示新的 dry-run 并取得精确删除授权。

## 真实数据与进程

- 禁止读取、修改或复制真实配置、数据库、Cookie、Token、媒体、账号资料和其他用户数据。
- 项目完整自检只同步启动本次命令直接拥有的 Python、Node 和无头测试浏览器子进程，不启动应用服务、用户浏览器或容器。
- 只管理本次启动且记录了所有权的进程，禁止按进程名称批量结束。
- fixture、缓存、日志和输出必须位于隔离临时目录或已确认的运行目录，不能写入真实持久化目录。
- 无需认证、不上传本地或非公开内容、不产生费用、不发布且不改变外部状态的有界公开只读联网，在来源、用途、规模和副作用已由当前任务或方案列明时，可以作为普通验证前置。
- 需要认证或私有资源、上传、外部写入、费用、明显大规模下载或特殊环境的项目必须在测试项中声明，并另行取得授权；不得用公开只读联网边界推导这些权限。

## 无头浏览器边界

- Playwright 是 T-PROJECT full 的必需阶段，只能复用已经存在的 Playwright Chromium、Chrome、Edge 或 Chromium；T-PROJECT 不安装、不下载也不更新浏览器。
- `BILI_PLAYWRIGHT_CHROMIUM` 只允许指向既有普通可执行文件。浏览器启动必须使用本次 run-id 下的新 profile、缓存和临时目录，禁止复用系统用户 profile、现有登录会话或已打开的浏览器实例。
- 浏览器测试只允许访问测试直接拥有的回环 HTTP 服务和本地静态资源；不得访问真实 Bilibili、真实部署地址或其他外部网络。
- runner 只能通过自己持有的 Playwright 句柄关闭本次浏览器进程。缺少或无法启动兼容浏览器时，严格入口记录 `blocked`；不得通过按名称结束现有浏览器或临时下载来继续。

## 敏感信息

测试输入只使用虚构凭据和隔离数据。日志、失败输出和交接摘要不得回显秘密或原始运行现场。
