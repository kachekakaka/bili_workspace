# BBDOWN-20260815：Windows 启动器 BBDown 子进程三处缺陷修复方案

- 待办 ID：`BBDOWN-20260815`
- 状态：`已完成`
- 治理路线：用户报告运行缺陷后的记录与修复规划
- 保存决定：用户于 2026-08-15 明确要求“保存方案然后 review 一下”
- 当前阶段：用户于 2026-08-15 实施验收通过并授权关闭；活动待办已退出，方案与归档索引已经形成历史导航
- 主责边界：Windows 启动器下 BBDown 子进程的弹窗、输出编码与登录态通路三处缺陷的记录与修复规划；不改变下载算法、API 协议或数据根布局

## 1. 背景与证据

用户报告三个缺陷：

1. 开启搜索画质预览或下载任务时弹出命令终端窗口；
2. 任务日志与界面中文乱码（截图证据：BBDown 日志行 `[2026-08-15 12:52:29.890] - …` 中的中文全部显示为 U+FFFD 替换符）；
3. 作品在 B 站官网可选 1080P，但工具的画质预览（最高可用 480P）与任务预检（低于最低要求而失败）均只见到 480P；此前脚本启动版本可正常下载 1080P，切换到 0.7.0 EXE 后回归。

### 1.1 根因证据

- BUG 1（弹窗）：`app/bbdown.py:217` `_run_streaming` 的 `subprocess.Popen` 与 `:349` `run_bbdown_info` 的 `subprocess.run` 在 Windows 上未设置 `CREATE_NO_WINDOW`，BBDown.exe 为控制台程序故弹出窗口。launcher 自身两处子进程调用（`launcher/bili_workspace_launcher/backend_process.py:504`、`commands.py:37`）均已正确使用该标志，证明这是遗漏而非设计。
- BUG 2（乱码）：BBDown 1.6.3 在 Windows 上重定向输出使用系统 ANSI 代码页（GBK）；`app/bbdown.py:232` 增量解码与 `:354` `encoding="utf-8"` 均按 UTF-8 解码且 `errors="replace"`，中文全部变为 U+FFFD 后写入任务日志。数字与 ASCII 不受影响，清晰度解析不受此缺陷影响。
- BUG 3（480P）：BBDown 1.6.3 `LoadCredentials`（BBDown 仓库 `BBDown/Program.Methods.cs`）只从 `Path.Combine(APP_DIR, "BBDown.data")` 读取 cookie，其中 `APP_DIR = Path.GetDirectoryName(Environment.ProcessPath)` 即 **BBDown.exe 所在目录**，不是工作目录。0.7.0 EXE 版把 BBDown.exe 放在只读资源目录（`backend_process.py:404`、`482` → `state.py:76` → `config.py:67`），BBDown.data 位于数据根 `config/bbdown`（`paths.py:241`），两目录分离导致 BBDown 永远读不到 cookie → 未登录 → 取流只返回 480P。脚本版 BBDown.exe 与 BBDown.data 同目录，故正常。
- 账号页“登录状态已在线验证”与 BBDown 未登录并存的原因：`CookieChecker`（`app/cookie.py:70-120`）由 Python 直接读取 BBDown.data 文件内容后调用 B 站 nav 接口验证，验证的是“cookie 字符串在 B 站侧有效”（数据有效），而 BBDown 进程找不到该文件（通路断），两者不矛盾。

### 1.2 关联既有边界

- README 已知边界已预告“BBDown 上游已停止维护，Bilibili 接口或扫码协议变化后可能需要替换下载适配层”；本方案不评估 B 站侧风控，只修复工具自身通路。

## 2. 差异、选项与用户决定

### 2.1 处理程度与待办粒度

- 用户决定：记录 + 形成修复方案，暂不改代码；三个缺陷合并为一个待办、一份方案（同源同文件 `app/bbdown.py`，共用修复与验证）。

### 2.2 BUG 1 修复方式

- 用户决定：`_run_streaming` 与 `run_bbdown_info` 两处补 `CREATE_NO_WINDOW`（与 launcher 自身用法一致）。无替代方案。

### 2.3 BUG 2 解码策略

- 选项 A：探测式解码——先按 UTF-8 严格解码，失败回退 GBK（cp936）；
- 选项 B：Windows 下固定按 GBK 解码；
- 选项 C：只修预览不修下载日志。
- 用户决定：选项 A，兼容 BBDown 两种输出模式与不同系统语言环境。

### 2.4 BUG 3 登录态通路

- 选项 A：每次调用显式传 `--cookie <cookie字符串>`（BBDown 官方支持，`SetUpWork` 中 `Config.COOKIE = myOption.Cookie` 直接生效）；
- 选项 B：每次调用前把 BBDown.data 同步到 BBDown.exe 所在目录（有则拷、无则删），并配套修改 launcher `verify_tree` 将该文件列为运行时凭据白名单，避免每次启动因“多出文件”触发完整资源重建（FFmpeg 数百 MB 重新解压校验）。
- 用户决定：选项 B。理由：cookie 不进命令行参数，避免进程列表可见性，自认更安全。BBDown 不支持指定 cookie 文件路径，只支持 `--cookie` 传字符串或 exe 目录固定文件，故选项 B 为“每次调用都取最新凭据”且不改变资源只读语义的实现。
- 已确认的技术事实：资源目录每次启动执行文件集合一致性校验（`resources.py:200-204`），多出的 BBDown.data 会触发重建（`resources.py:265-267`），因此白名单配套修改为必需；白名单只跳过运行时凭据文件，内置资源哈希校验语义不变。

### 2.5 EXE 交付范围

- 用户决定：方案实施包含按仓库构建链重建自用 EXE（`tools/build_launcher.py`），本地验证后替换 `dist`；不创建新 tag、GitHub Release 或 GHCR 正式镜像，符合项目“停止未来正式发布”边界。

## 3. 实施范围（获得实施授权后执行）

### 3.1 文件清单与改动内容

| 文件 | 动作 | 内容 |
| --- | --- | --- |
| `app/bbdown.py` | 修改 | `_run_streaming` Popen 与 `run_bbdown_info` subprocess.run 在 Windows 补 `CREATE_NO_WINDOW`；两处解码改为“UTF-8 严格解码失败回退 GBK”的探测式解码（需处理增量流分块边界：UTF-8 多字节序列跨块时当前块严格解码失败不得立即回退 GBK，应基于解码器状态或字节缓冲判断）；新增“每次调用前同步 BBDown.data 到 exe 目录”逻辑（有则原子拷贝、无则删除残留、失败容忍并记录日志、线程安全） |
| `launcher/bili_workspace_launcher/resources.py` | 修改 | `verify_tree` 增加运行时凭据白名单 `BBDown.data`，集合校验与摘要校验跳过该文件 |
| `tests/`（含 `test_bbdown_cmd.py` 等） | 修改/新增 | argv 与解码探测用例；同步逻辑用例（有拷无删、原子性、并发、失败容忍）；既有下载链路测试回归 |
| `launcher/tests/test_resources.py` | 修改/新增 | 白名单用例：资源目录存在 BBDown.data 时不报错、不触发重建；无白名单文件时行为不变 |
| `CHANGELOG.md` | 修改 | 未发布章节登记三处修复 |

### 3.2 不做的事

- 不改 BBDown 二进制、不升级 BBDown、不评估或修复 B 站侧风控；
- 不改变数据根布局、下载算法、API 协议；
- 不创建版本 tag、GitHub Release 或 GHCR 正式镜像。

## 4. 验证计划（普通验证层级）

- 单元测试：上述新增用例与既有相关测试（`test_quality.py`、`test_api_v04.py` 等下载链路）回归，全部使用注入 runner，不发起真实 B 站网络调用；
- 静态检查：仓库现有 lint/自检入口；
- EXE 构建冒烟：构建成功后启动 EXE、进入配置页并触发一次画质预览流程；真实 B 站取流与下载属于真实数据/正式认证，需另行明确授权，不在普通验证默认范围内；
- 用户验收：用户在替换后的 EXE 上复现原三个缺陷场景（预览无弹窗、日志无乱码、预览与下载可达 1080P）后关闭。

## 5. 收尾与联合复核（实例化任务值）

- 本方案主责与完成证明：三处代码修复与白名单落地、对应测试与回归通过、自用 EXE 重建并替换、用户复验三个场景通过。
- 覆盖与残余：覆盖搜索预览、任务预检、下载与日志显示；不覆盖 B 站侧风控与 BBDown 自身缺陷。
- 确定切片与就绪证明：切片为 `app/bbdown.py` 与 `launcher/resources.py` 两文件及其测试；就绪证明为单元测试与静态检查通过。
- 关闭时的状态消费者：需求文档已知边界（如需记录行为变化）、CHANGELOG 未发布章节、任务页日志展示。
- 关联方案、共享文件与对方职责状态：不适用，无其他活动方案依赖本切片。
- 联合只读复核触发条件：本方案为独立切片，无关联方案，不适用。
- 最终范围与漂移复核：实施时若发现新的根因分支或需要语义决定，停止并申请授权差额。
- 验收停点：用户复验三个场景并确认后进入关闭。
- 关闭边界与未运行验证：真实 B 站网络取流、正式发布物未在验证范围；关闭不推定 commit、push 或 PR。

## 6. 授权与边界

- 本方案保存不构成实施授权；
- 实施需用户按已确认方案明确授权，覆盖本方案列明的文件修改、测试、构建与替换；
- 真实 B 站网络调用、真实账号与媒体数据验证需另行授权。
