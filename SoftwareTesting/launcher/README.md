# Windows 单文件启动器测试

- Registry ID：`T-LAUNCHER`（`affected_only`）
- 触发条件：`launcher/`、启动器专用工具、应用路径/配置接线、Dockerfile、固定依赖、spec、CI 或启动器交付契约变化时执行对应阶段。
- 输入：`launcher/bili_workspace_launcher/`、`launcher/tests/`、`launcher/*.txt`、`launcher/*.spec`、FFmpeg 固定构建配方、`tools/build_ffmpeg_windows.py`、`tools/prepare_launcher_resources.py`、`tools/build_launcher.py`、`scripts/windows/build-launcher.bat` 及被内嵌的应用/Docker 上下文。
- 基线：Windows amd64、Python 3.11；纯逻辑阶段不要求 Docker、PySide6、真实产品数据或网络。
- 工作目录：项目根目录。

仓库本地只使用根目录唯一 `.venv`，不为应用、测试或启动器分别创建环境：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements\dev.lock -r launcher\requirements-dev.txt
.\.venv\Scripts\python.exe -m pip check
```

## 纯逻辑与安全边界

```text
.\.venv\Scripts\python.exe -B -X utf8 -m pytest -q launcher/tests
.\.venv\Scripts\python.exe -B -X utf8 -m ruff check launcher tools/build_ffmpeg_windows.py tools/prepare_launcher_resources.py tools/build_launcher.py
```

没有安装 PySide6 时，唯一 GUI offscreen 构造项允许明确显示为 `skipped`；其余数据根、设置、网络联动、资源哈希、子进程协议、BBDown 凭据目录、Docker 命令/事务与构建工具测试必须通过。测试只使用 pytest 临时目录和合成 Docker 输出，不启动后端、真实 Docker 或第三方下载工具。

## Windows 单文件候选

安装 `launcher/requirements-dev.txt` 后执行：

```text
.\.venv\Scripts\python.exe -B -X utf8 -m tools.build_launcher --dist-dir build/launcher-candidate --work-dir build/launcher-pyinstaller --resource-dir build/launcher-resources --record build/launcher-candidate.json
# 取得产品进程授权后再单独执行：
build\launcher-candidate\bili-workspace-launcher-0.7.0.exe --self-check
```

构建脚本默认不启动生成的 EXE；只有显式传入 `--run-exe-self-check` 才执行同一自检，正式 `dist/` 构建则强制要求该开关。构建过程只接受 Windows amd64 Python 3.11，获取清单固定且哈希匹配的 BBDown 与 FFmpeg 官方源码输入，执行内置工具版本冒烟，验证 PE AMD64、单文件命名、文件数量、低于 100 MiB 的停止线和资源清单，并在指定位置写候选记录。FFmpeg 必须由固定 Linux/amd64 容器、Debian 快照和仓库内配方自建，官方源码签名、发布公钥指纹、实际二进制、`ffmpeg -version` 配置、LGPL 模式、工具链、PE 导入、完整源码及许可证证据全部进入资源清单；缺失或不一致时在 PyInstaller 前失败关闭。固定依赖安装、公开资源获取、工具进程、候选构建及 EXE 自检分别遵守活动方案的授权停点；不能在缺少证据时把纯逻辑阶段替代为打包通过。

## 产品与 Docker 验收

产品验收按以下边界分别记录：

- 全新仓库外数据根、本机模式、局域网服务器模式、非法安全组合、端口冲突、托盘和 Windows 会话关闭；
- 没有系统 Python、BBDown、FFmpeg 且启动时断网时，EXE 仍能启动并使用内置工具；
- 真实 Docker Engine 生成规定的 `linux/amd64` tar、`.tar.sha256`、JSON，三者身份一致；中断恢复和精确临时镜像清理不调用通用 prune。

这些是产品或外部进程验证，不能作为普通测试擅自运行，也不能使用真实用户数据根、Cookie、数据库或媒体。这里的 Docker 阶段只承接启动器面向 `linux/amd64` 的 Docker 导出三件套及其事务、身份与恢复协议；当前项目镜像的一般 amd64／arm64 实际构建由 [T-DOCKER](../docker/README.md) 承接。

## 关键断言

- `launcher.json` 与 EXE 同级且只保存 schema、数据根和最近导出目录；删除后重新选择原数据根恢复网络与业务状态。
- 数据根必须在源码仓库和 EXE 控制根外，固定包含 `config/`、`userdata/`、`downloads/`，并让任务日志、通用缓存、.NET 展开缓存、HOME 与临时目录全部落在 `userdata/`；GUI 在写入标记、默认配置或网络设置前即持有数据根锁，并持续持有到退出；重解析逃逸、异常备份目标、损坏配置和未来 schema 失败关闭。
- BBDown/FFmpeg 工具位于已校验的 `resources/<build_id>/windows-tools/`，`BBDown.data` 只位于数据根 `config/bbdown/`；后端内部环境不回落到仓库路径。
- 本机模式只监听回环；局域网服务器模式显式管理监听、端口、可信 Host/代理、公开 URL、Secure Cookie、HSTS 和 IP Host，任何通配或非法联动都阻止启动；Web 设置页按 API 返回的 `protected_fields` 禁用并省略启动入口托管字段。
- 后端健康探测绕过系统代理，并同时匹配 HTTP 状态、`ok`、`build_id`、运行模式和仍存活的当前子进程；停止只操作当前 `Popen`、Job Object 与停止文件，调用方持有的数据根锁由 GUI 继续持有；端口冲突不结束其他进程，也不静默换端口。
- GUI 保留 500ms 子进程状态检测，但后端就绪后 HTTP 健康探测降为每 10 秒一次；异常退出后的 `work/backend-*` 只有在目录名、journal、固定文件集和已死亡 PID 全部匹配时才逐文件回收，任何额外条目、重解析点、活 PID 或不可判定状态均保留。
- 构建器发布已有 EXE 前使用 Windows Restart Manager 检查文件占用；占用时在改名或写记录之前失败，不产生“新 EXE 已发布但旧备份删不掉”的半成功状态。
- Docker 用户入口固定为 `linux/amd64`，覆盖确认绑定旧 Docker 导出三件套的精确大小和 SHA-256，三件套以 JSON 最后提交并能从 journal 恢复；Docker 不可达不能冒充“镜像不存在”，只清理同时匹配 journal、作业 label 与 build label 的自有临时 tag。
- 候选固定名为 `dist/bili-workspace-launcher-0.7.0.exe`，仓库最终只跟踪这一份当前 EXE；达到 100 MiB 时停止重新决策。

## 结果

适用阶段全部以退出码 `0` 完成才是 `passed`。断言失败为 `failed`；缺少已要求的 Windows/Python/固定依赖或授权为 `blocked`；GUI 被跳过、打包/产品/Docker阶段适用却未执行时为 `inconclusive`。动态候选哈希、运行时间、真实 Docker 镜像 ID 和人工验收记录留在仓库外证据中；`launcher/current-build.json` 只承接当前规范 EXE 的稳定身份。
