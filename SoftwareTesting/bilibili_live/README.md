# T-BILIBILI-LIVE：真实 Bilibili 影响域验证

本套件是 Windows 本地 `affected_only` 验证，只证明当前源码或受影响候选与真实 Bilibili 的关键成功链。普通 pytest、T-PROJECT 与 CI 仍只使用虚构凭据和模拟响应。

## 授权和准备

仓库长期真测授权位于当前 Git common directory 的 `bili-workspace/automatic-live-test.json`。它严格绑定 `project_id=bili_workspace`、凭据源和隔离测试根；同仓库 worktree 共享，clone、commit 和 push 不携带。只有维护者明确要求创建该文件才形成持续授权，删除文件即撤销。格式见[字段契约](../../docs/字段契约.md#t-bilibili-live-短期字段)。

授权绑定的凭据源还必须已有 `.bili-workspace-data-root.json`、普通文件 `config/bbdown/BBDown.data`，以及提供固定 UID/八个 BV 的 `.bili-workspace-live-test.json` 场景文件。场景文件不再单独代表仓库授权；运行器不会创建它、扫描数据根或读取其他业务文件。自动入口从仓库本地授权取得两个根，显式入口仍要求调用者同时提供 `-DataRoot` 和绝对 `BILI_TEST_ROOT`。

隔离测试根必须是专用仓库外目录，不得位于 `%LOCALAPPDATA%`，也不得与仓库或凭据源互相包含。每次运行会在其下新增唯一 run；产品、工具与浏览器子进程的 `HOME`、`USERPROFILE`、`LOCALAPPDATA`、`APPDATA`、临时目录和 .NET 缓存均重定向到该 run。非通过结果会保留整个 run，成功结果只删除其中全部 `BBDown.data` 副本。

## 入口和影响域

当前仓库已经具有本地授权时，从 PATH 中的 PowerShell 7 直接运行：

```powershell
pwsh -File scripts/windows/run-bilibili-live.ps1 `
  -Impact discovery
```

需要绕过仓库本地默认值进行一次显式运行时，仍可使用：

```powershell
$env:BILI_TEST_ROOT = 'E:\bili-workspace-live-runs'
pwsh -File scripts/windows/run-bilibili-live.ps1 `
  -DataRoot 'E:\bili-workspace-credential-source' `
  -Impact discovery
```

`-Impact` 的选择如下：

| 值 | 真实阶段 |
| --- | --- |
| `discovery` | 登录、UP 主名称搜索、资料、投稿分页、同 UID 八项、公开封面与响应结构 |
| `download` | discovery，加画质预检、严格 8 项批量、至少一项完整下载和入库 |
| `browser` | download，加真实页面名称搜索、封面、跨页选择、取消全量入库确认、概览鼠标/键盘入口 |
| `playback` | browser，加已入库媒体实际 Range 打开验证 |

普通开发验证使用 `-Target source`；下载阶段默认复制、自检当前正式 EXE，但只借它在 run 内展开已校验的 BBDown/FFmpeg，实际产品代码继续运行当前源码，因此普通源码改动不需要重新打包。需要验证另一份既有候选工具时，可在非 `discovery` 的源码目标显式传入 `-ToolProviderRecord <candidate-build.json>`。只有启动器、冻结资源、内嵌 Web 或工具布局受影响，且已经另行构建候选时，才使用 `-Target candidate -CandidateRecord <build.json>`；供后续真链使用的候选须由 T-LAUNCHER 的 `--keep-candidate` 明确保留。入口只复制并测试候选，不构建、不晋升、不改写正式 EXE 或规范记录，原候选 staging 的后续精确清理由 T-LAUNCHER 授权与所有权规则承接。

首次运行没有跟踪结构基线，或以后发现结构漂移时，会在 discovery 后以 `inconclusive` 停止，并在 run 的 `results/fixture-candidate/` 生成完整脱敏候选。review 后如明确授权写回，运行：

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m tools.bilibili_live refresh-fixtures --run-root '<精确 run 路径>'
```

写回后先运行相关模拟测试，再重新执行真链。`tests/test_bilibili_live_fixtures.py` 会在尚无基线时明确跳过；四类基线一旦写回，就逐个把全部结构变体送入当前名称搜索、UP 主资料、投稿和作品详情适配器，防止后续模拟又退回手工最小响应。刷新命令不提交或推送。

## 上限、结果和清理

下载固定并发 1，最多尝试固定场景中的 8 项；总运行 15 分钟、run 增长 2 GiB、开始下载前至少 5 GiB 可用空间。提交前会依据 BBDown 返回的共同画质、大小或码率，在剩余预算内为每项选择明确档位；完成后核对实际画质。上限到达时只通过 API 取消本次任务并等待本次拥有的进程；已有至少一项完整成功时可以通过，否则为 `inconclusive`。真实产品合同错误为 `failed`，登录、网络、风控、工具、磁盘或浏览器环境不足为 `blocked`。

只读列举满 72 小时的自有真链 run：

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m tools.bilibili_live list-stale --test-root '<BILI_TEST_ROOT>'
```

只有维护者明确指定删除某个精确 run 后才执行：

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m tools.bilibili_live cleanup `
  --test-root '<BILI_TEST_ROOT>' `
  --run-root '<精确 run 路径>' `
  --data-root '<凭据源根>'
```

72 小时只是人工清理资格，不是自动期限。命令不会删除测试根、凭据源或相邻目录。

## 真实响应边界

允许保留公开的名称搜索、UP 主资料、投稿和作品详情 JSON、下载结果与进程日志。禁止记录请求 header、Cookie、二维码载荷、原始 `/nav` 账号响应、WBI 签名查询值、响应 header、HAR 或完整网络流量。结构候选会替换全部真实值；若公开响应把真实动态值用作 JSON 字段名，则安全停止而不生成可写回候选。原始响应、固定场景和整个真链 run 均不得进入 Git；仓库本地授权只保存在 Git common directory。
