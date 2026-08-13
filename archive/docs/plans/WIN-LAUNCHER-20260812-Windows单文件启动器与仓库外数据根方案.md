# WIN-LAUNCHER-20260812：Windows 单文件启动器与仓库外数据根方案

- 状态：已完成
- 建立日期：2026-08-12
- 目标平台：Windows 10/11 amd64
- 应用版本：`0.7.0`；具体构建使用独立 `build_id`
- 测试层级：新增 `T-LAUNCHER | affected_only`；受影响的 `T-PROJECT` 与 `T-DOC` 按 Registry 和授权边界执行
- 验证影响域：冻结路径、外置数据根、网络安全配置、进程所有权、离线资源、单文件打包、Docker amd64 导出、源码布局、CI 与活动文档
- 具体验证项：目录与配置单元测试、资源哈希和失败关闭测试、子进程及端口冲突测试、Docker 命令与产物事务测试、PyInstaller 自检、干净目录产品冒烟、局域网安全冒烟、真实 Docker 导出验收、源码与文档定向门禁

本方案把已经确认的产品边界转换为可施工、可验收的任务。保存方案不授权产品代码实施、安装构建依赖、启动产品进程、真实 Docker 构建、全量测试、Git 提交、推送、PR 或发布。

## 1. 目标与非目标

### 1.1 目标

1. 用一份可直接复制运行的 `dist/bili-workspace-launcher-0.7.0.exe` 取代当前 Windows 便携运行链；仓库只跟踪这一份当前 EXE。
2. EXE 在没有系统 Python、BBDown 和 FFmpeg、且启动时不联网的条件下，能够选择数据根、准备内置资源并启动后端。
3. EXE 同时支持本机模式和显式启用的局域网服务器模式，并在图形界面中管理现有网络与安全设置。
4. 配置、SQLite、日志、凭据、缓存和媒体均进入用户选择的仓库外数据根；EXE 同级目录只保存可重建控制状态和内置资源的已校验展开副本。
5. EXE 统一承接下游 Docker 镜像构建与导出，只生成 `linux/amd64` 产物及其校验文件和清单。
6. 试运行版 EXE 通过验收后，精确删除现有 Windows 启动脚本、便携运行时、旧引导器及其专用验证链，并把仍有价值的验证职责迁入新测试套件。

### 1.2 非目标

- 不实现 EXE 自构建、自更新、自动下载新版本或应用内更新。
- 不做旧数据识别、复制、转换、导入、兼容迁移或清理；用户自行选择现有或新数据目录。
- 不提供 x86、arm64 或多架构 EXE，不让用户选择 Docker 架构。
- 不创建 Windows 服务、计划任务、开机自启、tag、GitHub Release 或 GHCR 镜像。
- 不内置 Docker Engine，也不提供 Docker 的通用镜像、容器、卷或构建缓存清理功能。
- 不删除、移动或改写仓库中被 Git 忽略的真实配置、用户数据库、媒体内容。
- 不自动删除既存且未跟踪的 `.runtime/`、`.env`、`dist/` 旧试运行文件或其他所有权不明的本地残留；本次用户另行明确确认不再使用旧便携工具目录，因此只在精确解析后清理了该目录中的旧工具副本。

## 2. 已确认的硬约束

| 主题 | 施工约束 | 决策依据 |
| --- | --- | --- |
| 网络模式 | 保留本机和局域网服务器模式；局域网模式不能以通配符或隐式降级绕过安全配置 | [ADR 0003](../../../docs/adr/0003-windows-launcher-keeps-lan-server-mode.md) |
| 构建边界 | EXE 只编排下游交付物，不构建自己 | [ADR 0004](../../../docs/adr/0004-launcher-builds-downstream-artifacts-only.md) |
| 数据位置 | 首次启动必须选择仓库外数据根；取消选择即不启动 | [ADR 0005](../../../docs/adr/0005-runtime-data-must-live-outside-the-repository.md) |
| 控制状态 | `launcher.json`、`resources/`、`work/` 与 EXE 同级；丢失控制状态只重新选择目录 | [ADR 0006](../../../docs/adr/0006-launcher-control-root-follows-the-executable.md) |
| Docker 架构 | 只构建并导出 `linux/amd64` | [ADR 0007](../../../docs/adr/0007-launcher-exports-amd64-docker-images.md) |
| 仓库二进制 | 只跟踪当前命名的一份 EXE；超出常规 Git 托管单文件上限时停止重新决策 | [ADR 0008](../../../docs/adr/0008-track-one-current-windows-launcher.md) |
| 旧链退出 | 试运行版 EXE 验收后，旧 Windows 便携运行链全部退役 | [ADR 0009](../../../docs/adr/0009-windows-exe-replaces-the-portable-runtime-chain.md) |
| 安全配置 | 网络与安全设置由数据根拥有，重新选择原数据根即可恢复 | [ADR 0010](../../../docs/adr/0010-data-root-owns-network-and-security-settings.md) |
| 离线工具 | 固定版本 BBDown 与 FFmpeg 嵌入 EXE 并经过哈希校验后展开 | [ADR 0011](../../../docs/adr/0011-launcher-embeds-bbdown-and-ffmpeg.md) |
| Python 基线 | 本地开发、测试、启动器、CI 与 Docker 统一使用 Python 3.11；仓库内共用唯一 `.venv` | [ADR 0012](../../../docs/adr/0012-repository-uses-one-python-311-baseline.md) |

“完全离线自带工具”限定为 Windows 应用运行和下载所需的 Python、前端、BBDown 与 FFmpeg。Docker 导出仍要求机器上已有可用的 Docker Desktop/Engine；本方案不把 Docker Engine、全部 Linux 基础镜像或任意第三方构建缓存塞入 EXE，也不把首次 Docker 构建无条件表述为断网可完成。

本文使用“试运行版 EXE”表示旧 Windows 链仍保留时构建、用于产品验证的可运行包；使用“最终版 EXE”表示旧链退出并完成引用改写后，从最终源码树重新构建的规范交付物。两者是同一个产品入口的不同验证阶段，不是迁移工具或两套产品。

## 3. 目标目录与所有权

### 3.1 仓库结构

```text
launcher/
  bili_workspace_launcher/
    __init__.py
    __main__.py
    backend_process.py
    cli.py
    constants.py
    docker_jobs.py
    gui.py
    paths.py
    ports.py
    resources.py
    settings.py
    version.py
  tests/
  bili-workspace-launcher.spec
  current-build.json
  requirements.txt
  requirements-dev.txt
  THIRD_PARTY_NOTICES.txt
tools/
  build_launcher.py
  prepare_launcher_resources.py
scripts/windows/
  build-launcher.bat
SoftwareTesting/launcher/README.md
dist/
  bili-workspace-launcher-0.7.0.exe
```

模块名称可在不改变职责边界的前提下小幅调整；`dist/bili-workspace-launcher-0.7.0.exe`、`launcher/current-build.json` 和测试入口属于稳定契约。`.gitignore` 只放行该规范 EXE，并继续忽略它同级运行产生的 `launcher.json`、`resources/`、`work/` 及其他非规范产物。

### 3.2 EXE 同级控制根

```text
<launcher-dir>/
  bili-workspace-launcher-0.7.0.exe
  launcher.json
  resources/<build_id>/...
  work/<job_id>/...
```

- `launcher.json` 使用 schema 1，只保存最近一次数据根和最近一次导出目录等便利状态；不保存 Cookie、密码、Token、网络安全值或业务数据。
- `resources/<build_id>/` 只能由当前 EXE 的资源清单生成。先展开到任务临时目录，逐文件校验大小与 SHA-256，再原子发布；不完整、哈希不符或不可写时失败关闭。
- `work/<job_id>/` 只保存当前启动器拥有的可恢复任务记录和临时文件。清理必须同时通过路径归属、任务 journal 与所有权标识，不能对目录做宽泛清扫。
- EXE 所在目录不可写时明确报错并停止，不静默切到 `%LOCALAPPDATA%` 或其他公共目录。

### 3.3 用户选择的数据根

```text
<data-root>/
  .bili-workspace-data-root.json
  config/
    config.json
    runtime.env
    tags.json
    bbdown/BBDown.data
  userdata/
    bili_workspace.db
    cache/
      covers/
      compatible/
      dotnet/
    tmp/exports/
    logs/backend.log
    task_logs/
    indexes/
    home/
    backups/
  downloads/
```

- 首次启动、`launcher.json` 不存在或其中目录不可用时，必须重新选择；取消选择不启动后端。已记住的数据根也在每次启动时重新校验，不能把一次选择当成永久信任。
- 选择器拒绝 EXE 控制根内部、任意 Git 工作树内部、文件而非目录、不可创建/不可写、重解析后落入上述禁区的路径。路径检查使用规范化绝对路径并处理 Windows junction/symlink/reparse point；固定子目录也要逐一复核，拒绝经重解析点逃出数据根或回到仓库/控制根。
- 标记文件仅记录非敏感 schema、产品标识和创建信息。已存在的合法数据根只补齐缺失的固定子目录和默认配置；损坏配置、类型冲突或未来 schema 均失败关闭。
- 选择已有目录不触发迁移，不扫描其他旧目录，不覆盖现有值。删除 `launcher.json` 后重新选择原数据根，应恢复原配置和数据。

## 4. 应用与配置接线

1. 把当前“源码根既是资源根又是数据根”的假设拆为四个显式职责：只读应用资源、数据根、控制根、下游任务工作区。冻结运行时通过 PyInstaller 资源目录读取 `app/` 与 `web/`，不能用 EXE 同级目录猜测 Web 资源。
2. 应用启动必须由显式环境/参数取得 `config/`、`userdata/` 与 `downloads/`。没有启动器注入且不是明确 Docker 模式时，不再自动把仓库根当成生产数据根。
3. 将 BBDown 的“可执行工具目录”和“凭据/工作目录”拆开。Windows 使用控制根下的已校验工具绝对路径，但让 BBDown 在数据根 `config/bbdown/` 下读写 `BBDown.data`；Docker 可在未显式拆分时让两者兼容地指向同一容器目录。
4. 当前默认模板从仓库根 `config/` 移到只读应用默认资源中；Windows 首启与 Docker 初始化共用一套确定模板。同步仍保留未知字段、空字符串、`0`、`false` 和已有用户值，并继续拒绝符号链接目标及损坏配置。
5. `runtime.env` 是网络运行值的唯一持久真源；`config.json` 只保存下载行为和界面可配置项。旧 `host`、`port`、`download_dir`、`bbdown_dir` 字段可以作为未知字段原样保留，但不再驱动运行，也不再由 Web 设置页写入；端口只由启动器网络设置写入，三个数据子目录和 BBDown 工具位置不可改写。
6. 网络配置保存在数据根：本机模式固定回环监听；局域网模式由 GUI 管理监听地址、端口、可信 Host、可信代理、是否允许 IP Host、公开 URL、Secure Cookie 和 HSTS。模式切换执行联动校验，禁止通配可信 Host/代理，HSTS 只有在已验证 HTTPS 前提满足时才能启用；非法组合不能启动服务，两个模式都不放松现有网站账号认证。
7. 启动器到后端的内部接线显式传入 `BILI_CONFIG_DIR`、`BILI_USERDATA_DIR`、`BILI_MEDIA_DIR`、BBDown 工具目录和 BBDown 凭据目录，并把 `HOME`、通用缓存、.NET 单文件展开缓存及临时目录约束到数据根；新增名称使用 launcher-child 私有契约并写入字段文档。现有 `BILI_BBDOWN_DIR` 只在 Docker/源码兼容入口中保留明确回退，不能与新路径产生双重优先级。
8. `APP_VERSION` 保持 `0.7.0`。`build_id` 改由构建时嵌入的源码与资源清单确定，冻结应用不得扫描现场仓库计算身份；GUI、后端信息接口、资源目录、Docker 清单和 `launcher/current-build.json` 使用同一身份。

路径改造必须显式审计 `app/paths.py`、`runtime.py`、`main.py`、`build_info.py`、`config.py`、`state.py`、`userdata.py`、`task_logs.py`、`tag_store.py`、`cookie.py`、`qr_login.py`、`api.py`、`enhancement_api.py` 和 `nas.py`，以及所有直接拼接仓库根或提及旧入口的测试/工具。只改启动入口而让这些模块继续回退到仓库根，不算完成。

## 5. 启动器生命周期

- GUI 打开后验证控制根、数据根、配置与资源，再自动启动唯一后端子进程；启动失败保留窗口并给出可行动错误，不进入假运行状态。
- 后端通过同一 EXE 的内部 `--run-backend` 子命令启动，使用构建内 Python 和应用资源，不调用系统 `python.exe`。该子命令只接受启动器生成的短期令牌和显式路径，不能成为绕过数据根/配置校验的第二个日常入口。
- 关闭主窗口只最小化到托盘；托盘“退出”或 Windows 会话关闭才停止由本次启动器拥有的后端。默认不注册开机启动。
- 子进程所有权至少绑定 PID、创建时间和本次随机令牌；优先使用 Windows Job Object 确保父进程异常退出时收口。任何停止动作都必须验证所有权，不能按端口或进程名结束其他程序。
- GUI 在启动后端前持有数据根级操作系统独占文件锁，防止不同目录中的两份 EXE 同时写同一 SQLite/配置；锁冲突只报告记录的 PID、创建时间和随机所有权令牌，不结束对方进程。锁文件可以留存，但进程退出后由操作系统释放的锁才是能否重新取得所有权的权威依据，不能只凭文件存在、PID 或端口判断。
- 端口被占用时不自动杀进程，也不静默换端口；GUI 展示冲突并推荐一个空闲端口，由用户确认后写回数据根配置。
- 启动、停止和日志尾部采用有界等待及有界读取；秘密值和完整 Cookie 进入统一脱敏路径。

## 6. 单文件与离线资源构建

1. 全仓以 Python 3.11 为唯一 Python 基线，本地开发、测试和 EXE 构建共用仓库根唯一 `.venv`；CI 只设置 Python 3.11，Docker 使用与相邻 `hg_workspace` 相同的固定 Python 3.11 镜像。启动器附加依赖锁定 `PySide6==6.11.1`、`PyInstaller==6.22.0`，应用运行依赖继续共用 `requirements/runtime.lock`，不再维护 3.12/3.13 兼容矩阵或独立 3.13 运行链。
2. `prepare_launcher_resources.py` 只接受清单固定的公开 BBDown/FFmpeg 来源或已验证缓存，核对版本、大小、SHA-256 和许可证，再生成嵌入资源清单；来源、哈希或许可证发生实质变化时停止重新确认。
3. `build_launcher.py` 在隔离 staging 中生成单文件 amd64 EXE，执行 PE 架构、内嵌清单、版本、资源摘要、单文件数量、文件名和大小检查；不在构建时读取真实配置或数据。
4. `build_id` 由规范化源码清单和嵌入资源摘要计算，排除 EXE、`current-build.json`、构建时间和其他输出，避免循环身份；除非另有证据，不把相同 `build_id` 宣称为不同机器生成的 EXE 逐字节可复现。
5. `launcher/current-build.json` 在最终版 EXE 生成后记录版本、`build_id`、该 EXE 的 SHA-256、字节数、平台、资源摘要和构建工具版本。规范 EXE 必须小于 `104857600` 字节；达到或超过该值时不启用 Git LFS、不拆分、不外发，停止重新决策。
6. CI 只从相同源码/资源输入复核构建身份、自检并上传短期验证 artifact；不写回仓库、不创建 tag/Release、不推 GHCR。仓库中规范 EXE 的更新由获授权的本地实施明确完成。
7. BBDown、FFmpeg、Qt/PySide6 及其传递二进制的许可证与 notice 在试运行版 EXE 接受前核对并随源码记录；不能通过许可证核对即不能收口。

安装固定构建依赖需要单独授权。按已确认方案实施时，只有方案列明、无需认证且哈希固定的普通公开资源下载可按项目规则执行；明显大规模下载、来源变更或额外联网仍需补充授权。

## 7. Docker amd64 导出事务

GUI 只提供一个固定 `linux/amd64` 导出动作。任务输入是当前 EXE 内嵌的确定源码/构建上下文和当前 `build_id`，不读取用户配置、Cookie、SQLite、媒体或仓库现场文件。

输出目录由用户选择，成功结果恰好为：

```text
bili-workspace-0.7.0-<build_id>-linux-amd64.tar
bili-workspace-0.7.0-<build_id>-linux-amd64.tar.sha256
bili-workspace-0.7.0-<build_id>-linux-amd64.json
```

JSON 至少包含 `version`、`build_id`、`platform`、镜像 ID、字节数、SHA-256 和 UTC 构建时间。流程为：

1. 在 `work/<job_id>/` 建立 journal，并用当前启动器、`job_id`、版本和 `build_id` 标签构建唯一临时镜像；命令固定声明 `--platform linux/amd64`。
2. `docker image inspect` 同时核对镜像 ID、OS、架构和所有权标签；不符即失败，不能导出。
3. 先写临时 tar，完成后计算 SHA-256 并生成临时校验文件/JSON；逐一验证可读性、字段一致性和 tar 中镜像身份。
4. 目标同名文件存在时先向用户展示精确路径、大小和构建身份并取得本次覆盖确认。发布前把旧三件套的身份与备份位置写入持久 journal，依次替换 tar、校验文件，并以 JSON 最后替换作为提交标记；中断时 GUI 不报告成功，下一次启动先按 journal 恢复最后一套完整旧产物或完成已验证的新产物，未恢复前禁止再次导出。
5. 成功后只删除标签和 journal 都证明属于本任务的临时 tag；失败可重试当前会话任务。退出时也只清理由当前 journal 精确证明所有权的临时对象。

三件套的消费者必须同时验证 JSON 身份、`.sha256` 与 tar；未完成 journal 恢复的文件不属于有效交付物。Windows 文件系统不提供跨三个文件的原子替换，因此验收证明“可检测、可恢复且不把混合状态判成功”，不虚构瞬时跨文件原子性。

不调用 `docker system prune`、`image prune`、`builder prune`，不删除卷、构建缓存、其他镜像或其他会话任务。真实 Docker 构建与导出属于产品级外部进程验证，执行前单独取得授权。

## 8. 旧链退役的精确边界

先完成不删除旧链的试运行版 EXE 及冒烟；只有试运行版 EXE 被用户接受，才实施以下 Git 跟踪项退出。被 Git 忽略的真实数据永不纳入删除范围。

最终实现还必须用隔离测试证明：即使工作树中仍存在被忽略的 `.runtime/`、`.env`、旧 `BBDown_portable` 内容或旧数据目录，新 EXE 与新源码入口也不会发现、执行或写入它们。这样把“旧链退役”落实为无活动消费者，而不借机清理所有权不明的本地文件。

### 8.1 精确删除

- 根入口：`start.bat`、`verify.bat`、`.env.default`
- 旧 workflow：`.github/workflows/build-integrated-runtime.yml`
- 便携工具与预制包：整个 `BBDown_portable/`、整个 `vendor/windows/`
- 仓库数据占位：`downloads/.gitkeep`、`userdata/.gitkeep`、`userdata/README.md`
- 旧 Windows 运行脚本：`scripts/windows/bilibili-login.bat`、`bootstrap-portable.ps1`、`bootstrap-runtime.bat`、`configure-network.bat`、`prepare-runtime.bat`
- 旧专用工具：`tools/build_integrated_runtime.py`、`tools/configure_network.py`、`tools/server_instance.py`、`tools/start_info.py`
- 旧专用测试：`tests/test_configure_network.py`、`tests/test_integrated_runtime.py`、`tests/test_server_instance.py`；删除前把仍有效的职责迁入 launcher/data-root 测试

`scripts/windows/new-test-run.ps1` 是测试隔离基础设施，不属于旧运行链，保留并按新目录契约更新。

### 8.2 精确迁移与改写

- 将 `config/config.json.default`、`config/runtime.env.default`、`config/tags.json.default` 的有效内容迁入只读应用默认资源；更新 Dockerfile、配置同步和测试后，删除这些旧路径以及 `config/README.md`。不触碰同目录被忽略的实际文件。
- 更新 `.gitignore`、`.gitattributes`、`tools/verify_source.py`、源码布局测试、版本验证测试、项目隔离测试、CI、第三方 notice、README、构建与运维文档，删除所有对已退役入口和 pack 的有效引用。
- 将 Windows 验证改为开发者/CI 专用的 launcher 构建与自检入口；不以另一个日常 `.bat` 启动链替代 EXE。

试运行版 EXE 通过后才删除旧项；删除后的最终版 EXE 必须从最终源码树重新构建并重复自检。最终版 EXE 失败时保留工作区变更、停止收口，不把试运行版 EXE 冒充最终交付物，也不自动回写或恢复任何真实数据。

## 9. 分阶段实施顺序

1. **契约与失败测试**：先登记 `T-LAUNCHER`，建立目录、配置、资源、进程、Docker 事务和构建清单的失败测试。
2. **路径解耦**：改造应用资源/数据/控制/工作区接线，拆分 BBDown 工具和凭据目录，并维持 Docker 兼容路径。
3. **启动器核心**：实现 schema、数据根校验、资源展开、端口检测、后端所有权和 CLI；再接入 GUI、托盘与网络安全配置。
4. **下游导出**：实现固定 amd64 Docker 任务、journal、三件套产物、覆盖事务和精确清理。
5. **构建链**：加入固定依赖、资源准备、PyInstaller spec、本地构建脚本、CI 短期 artifact 和 `current-build.json` 校验。
6. **普通验证**：执行单元、模拟外部命令、源码布局和选定文档门禁；不启动真实产品或 Docker。
7. **授权停点一**：取得安装依赖、必要公开资源和构建试运行版 EXE 的差额授权；验证 EXE 架构、身份、哈希、大小与离线资源。
8. **授权停点二**：取得产品进程授权，在全新临时数据根执行本机和局域网安全冒烟；不得使用真实数据根或凭据。
9. **用户验收停点**：由用户接受试运行版 EXE 后，才按第 8 节删除旧链并完成所有引用改写。
10. **最终版 EXE**：从最终树重建，复验单文件、干净目录启动、`launcher.json` 丢失重选、数据根归属和许可证。
11. **授权停点三**：取得真实 Docker 构建/导出授权，验证固定 amd64、三件套一致性、覆盖失败回滚和精确清理。
12. **文档与关闭**：按真实结果更新长期真源、测试记录和待办生命周期；未满足任何验收项时不关闭。

## 10. 验证矩阵

| 层面 | 必须证明 | 普通验证 | 需额外授权的验证 |
| --- | --- | --- | --- |
| 数据根 | 仓库内、控制根内、不可写、损坏和未来 schema 均失败关闭；合法目录固定落位 | 临时目录单元测试 | 干净 Windows 产品冒烟 |
| 配置安全 | 原值保留、非法组合不启动、删除 `launcher.json` 不丢配置 | 配置/环境合并测试 | 局域网设备访问与 HTTPS/HSTS 场景 |
| 离线资源 | 无系统 Python/BBDown/FFmpeg；展开前后哈希一致，破损即停止 | 资源清单与篡改测试 | 无网络干净机 EXE 冒烟 |
| 进程 | 只管理自己创建的后端，端口冲突不杀其他进程 | 子进程 mock、所有权令牌与超时测试 | Windows Job Object、托盘、会话关闭冒烟 |
| Docker | 命令固定 amd64；三件套同一身份；混合状态不判成功且可恢复；不做通用清理 | 命令生成、inspect 解析、事务与 journal 测试 | 真实 Docker build/save/inspect 与失败注入 |
| 交付物 | 唯一规范 EXE、PE amd64、版本/build_id/哈希一致、低于大小上限 | 构建产物静态自检 | 最终版 EXE 运行验收 |
| 仓库 | 旧链和有效引用退出；忽略数据不被触碰；CI 无发布权限 | 源码布局、定向文档规则、`git diff --check` | 全量测试或正式认证 |

拟新增 `SoftwareTesting/launcher/README.md`，并在 `docs/软件测试.md` 登记 `T-LAUNCHER | affected_only`。它至少覆盖 launcher 单元测试、资源准备、PyInstaller build/selfcheck 与可复现的临时目录冒烟；真实 Docker 与局域网设备场景以显式人工/产品验收记录承接，不伪装为普通单元测试结果。

## 11. 完成条件与回退

只有同时满足以下条件才能把待办关闭：

- 最终树能生成且仓库只跟踪 `dist/bili-workspace-launcher-0.7.0.exe` 这一份当前 EXE，`current-build.json` 与其一致，文件低于确定上限。
- 干净 Windows amd64 环境无需系统 Python、BBDown、FFmpeg 或启动时联网即可运行；数据根选择、固定目录、控制状态丢失重选均通过。
- 本机和局域网模式均按安全规则工作；非法配置失败关闭，Cookie/HSTS/可信边界没有回退。
- 真实 Docker 验收生成且只生成规定的 amd64 三件套；覆盖、失败回滚和所有权清理通过。
- 第 8 节旧链及有效引用全部退出，保留的验证职责在新套件中有可追踪承接；真实忽略数据未被修改。
- README、需求、设计、字段契约、运维、测试 Registry、第三方 notice 和 CHANGELOG 与最终实现一致；没有宣称新的正式发布。

实施失败时不迁移或回写数据。试运行阶段继续保留旧链；切换后的代码回退只通过后续明确授权的源码变更处理，数据根格式若未改变可继续保留，但不得把“可保留”扩展成自动兼容或迁移承诺。

## 12. 收尾与联合复核

- 本方案主责与完成证明：Windows amd64 单文件启动器、仓库外数据根、离线工具、固定 Docker 导出及旧链退役；由第 10 节矩阵和第 11 节条件证明。
- 关闭时的状态消费者：`README.md`、`docs/需求文档.md`、`docs/设计文档.md`、`docs/字段契约.md`、`docs/软件测试.md`、运维文档、`CHANGELOG.md`、源码验证与 CI。
- 关联方案、共享文件与对方职责状态：不适用；当前只有 `WIN-LAUNCHER-20260812` 一份活动方案承担该变更。
- 联合只读复核触发条件：旧链删除完成、最终版 EXE 自检通过且所有长期文档已改写后，复核 Git 跟踪布局、残留引用、构建清单和验证证据。
- 验收停点：试运行版 EXE 用户接受和产品进程冒烟已经完成；真实 Docker 导出仍是按需单独执行的产品验收，不能由普通测试结果代替。
- 关闭边界与未运行验证：本方案保存和 Review 不运行产品、Docker、全量测试或正式认证；关闭时逐项记录实际已运行与仍未运行验证，不因文档和静态门禁通过而宣称功能完成。

完成后，待办退出活动入口；需要保留本方案时，将其完整移动到归档并更新归档索引。该关闭动作不推定 commit、push、PR、tag、Release 或任何发布授权。

## 13. 方案 Review（2026-08-12）

| Review 维度 | 结论 | 已落实的防线 |
| --- | --- | --- |
| 范围闭合 | 通过 | 明确 EXE 只构建下游产物；离线边界不包含 Docker Engine；无迁移、自更新、多架构或发布扩张 |
| 代码接线 | 通过 | 列出所有当前仓库根依赖模块；拆分只读资源、数据、控制、工作区以及 BBDown 工具/凭据职责 |
| 数据与网络安全 | 通过 | 每次启动复核数据根及固定子目录；网络值只有一个持久真源；保留账号、Host、代理、Cookie 与 HSTS 失败关闭规则 |
| 生命周期 | 通过 | 同一 EXE 内部后端模式、数据根独占锁、Job Object 与三元所有权共同避免重复写入和误杀进程 |
| 交付事务 | 通过 | 构建身份避免循环哈希；Docker 三件套承认可检测/可恢复事务，不声称文件系统不具备的跨文件原子性 |
| 删除与回退 | 通过 | 先构建试运行版 EXE 并完成用户验收，再精确退出 Git 跟踪旧链；忽略残留无活动消费者，但不越权删除本地文件或真实数据 |
| 验证与关闭 | 通过 | 普通测试、产品冒烟、真实 Docker、用户验收和文档关闭分层，任何静态结果都不能替代高副作用验收 |

Review 未发现仍需用户作语义选择的问题。剩余不确定性是 EXE 体积、第三方许可证、Windows 产品冒烟和真实 Docker 导出能否提供通过证据；它们属于实施证据或授权停点，失败时按本方案停止，不现场改换产品边界。

## 14. 实施进度与复核（2026-08-13）

试运行阶段的源码实现、固定资源准备、普通验证和 EXE 构建已经完成：应用资源、数据根、控制根和任务工作区已经解耦；启动器 GUI、同一 EXE 内部后端、数据根锁、Job Object、网络安全配置、离线资源展开、固定 amd64 Docker 导出事务、PyInstaller 构建入口、短期 CI artifact 和测试入口已经落入工作树。Web 设置页按 API 的 `protected_fields` 处理启动入口托管字段；GUI 在写入数据根标记、默认配置或网络设置之前取得独占锁并持有到退出；后端健康探测核对当前进程、模式和 `build_id`，且一次性启动令牌不会传给第三方后代进程。Docker 覆盖确认绑定旧文件的大小与 SHA-256，失败 journal 保留并脱敏，守护进程不可达不会被误判为镜像不存在。

全仓已经按 [ADR 0012](../../../docs/adr/0012-repository-uses-one-python-311-baseline.md) 收敛到 Python 3.11：仓库根唯一 `.venv` 使用 Windows amd64 Python 3.11.1，并同时安装应用开发测试依赖、PySide6 6.11.1、PyInstaller 6.22.0 与 pytest 9.0.2；主 CI 的全部 Python 作业和启动器 CI 只设置 3.11，Docker 使用与相邻 `hg_workspace` 相同的固定 Python 3.11 镜像摘要。旧便携包中的 Python 3.13.14 已随旧链退役，不再是源码、Docker、主 CI 或 EXE 的运行边界。

固定资源与分发证据已经形成并由构建器和 EXE 自检共同核对：

- BBDown Windows 1.6.3 固定包为 8,040,728 字节，SHA-256 为 `40f1e2af0d4e74df765c6f93d2e931f9bea201d5168d0bc62dc35a54b7e0ec02`；Dockerfile 同时固定了 Linux x64 与 arm64 包的实际摘要，不再保留空摘要；
- FFmpeg 7.1.1 来自官方源码归档、分离签名与固定发布公钥，在固定 `linux/amd64` Debian 快照容器中交叉构建 Windows amd64 二进制；构建未启用 GPL、nonfree、version3 或外部 `--enable-lib*`，记录许可模式为 LGPL-2.1-or-later；生成的 `ffmpeg.exe` 为 22,395,904 字节，SHA-256 为 `bab874b6e6c7fae4d843f982e6cf686ebbe213bffa5f50769ec6c1ff39dd6b55`，PE 导入仅含系统 DLL，实际 `h264_mf`/AAC 一秒 MP4 转码冒烟通过；
- PySide6 wheel 的元数据只带商业许可引用，构建链因此另行固定并嵌入 Qt for Python 6.11.1 官方 GPL、LGPL 与 Qt GPL exception 三份许可正文，逐份核对 URL、大小和 SHA-256；没有放宽许可门禁；
- 资源清单同时嵌入 FFmpeg 对应完整源码、签名、公钥、构建配方、工具链清单、版本配置、二进制身份、兼容转码记录和第三方 notice；任一项缺失或不一致都会在 PyInstaller 发布前或 EXE 自检时失败关闭。

本轮实际完成的普通验证与试运行版 EXE 证据如下；真实 Docker 导出仍未启动：

- `ruff` 对 `launcher/`、三个启动器构建工具与受影响的 `app/nas.py` 通过；
- 根目录统一 `.venv` 的 Python 3.11 启动器套件为 79 passed、1 skipped；唯一跳过项是当前 Windows 测试环境不具备符号链接创建能力，PySide6 offscreen GUI 构造项已实际通过；Docker、CI、仓库布局与旧链过渡契约定向测试为 33 passed；
- 受影响配置、布局、认证、运行模式、迁移与设置 UI 为 49 passed、1 skipped；受影响 API、配置、BBDown、完整性、运行实例、Docker 与测试隔离为 50 passed、3 skipped，另有一条既有损坏配置备份恢复警告；
- `tools/verify_source.py` 通过；T-DOC 规则夹具 29 项通过；目标文档门禁为 0 warning；`git diff --check` 通过；
- 最终复测的试运行版 EXE 为 `build/launcher-smoke-final/bili-workspace-launcher-0.7.0.exe`，平台 `windows/amd64`，`build_id` 为 `663052a275a2`，大小 83,403,230 字节，SHA-256 为 `de6f066341fcd542f73770ae0b215300a9458f6d32da55bec02ada9690476b5e`，资源清单 SHA-256 为 `4b1b165791f49db649d78d1e8b2d462b2ae1917b7a52f8d47cfa39c2721560df`；构建日志确认解释器来自仓库根 `.venv`，PE amd64、单文件名、100 MiB 停止线及内部 `--self-check` 均通过。
- 产品冒烟只使用 `%LOCALAPPDATA%\Temp\bili-workspace-launcher-smoke-20260813-e2e1ae47862a` 下的任务专属控制根与数据根；本机模式健康检查、默认临时密码首次改密拦截、新密码登录、旧密码失效、主界面和设置页、数据库/日志/媒体/缓存路径归属均通过，浏览器控制台无错误。
- 局域网模式实际监听 `0.0.0.0`，回环和当前 Wi-Fi IPv4 均可访问，未知 Host 返回 400，匿名受保护 API 返回 401；HTTP 配置不错误启用 Secure/HSTS，HTTPS 反代配置则使用 `__Host-` Secure/HttpOnly/SameSite Cookie 并返回 HSTS。通配 Host、`0.0.0.0/0` 可信代理、HTTP+HSTS、HTTPS 未开 Secure Cookie 四种非法组合均没有创建后端监听。
- 受控端口冲突没有停止占用者、抢占端口或静默改写配置；可见 GUI 的“退出程序”会停止自有后端、释放监听与数据根锁。强制结束父启动器后，Windows Job Object 会带走子进程和监听；下一次启动只回收严格匹配且 PID 已死亡的遗留后端会话。

实施复核发现并修复了预案未能由普通 happy-path 直接暴露的边界：数据根原先在 GUI 写配置后才加锁；启动器本机模式下 Web 设置页仍会提交受保护端口和下载目录；健康探测未绑定具体 `build_id`/模式且可能受系统代理影响；一次性令牌可能被 BBDown/FFmpeg 继承且其摘要比较未使用常量时间原语；EXE 同级可写探针在中途失败时可能残留；Docker 构建失败可能由二次 inspect 覆盖原错误并误删 journal；下载响应和 Docker tar/三件套小文件读取缺少完整的有界读取；启动器子进程仍注入旧 `BILI_BBDOWN_DIR`；Git 工作树边界和数据根边界没有把异常 `.git` 重解析点视为边界。产品试跑又发现就绪后的 500ms 健康请求会持续积累短连接、异常退出会遗留控制会话，以及 Windows 可在运行中的旧 EXE 被改名后拒绝删除备份而造成发布半成功；现已分别改为 10 秒健康请求、严格死亡会话回收和发布前 Restart Manager 占用门禁。对应修复和回归断言均已加入，试运行版 EXE 已在这些修复及全仓 Python 3.11 统一之后重建。

用户已确认试运行结果，并授权旧 Windows 链全部退役。本次收口已删除第 8 节列明的根批处理、Portable Python/媒体 packs、旧运行脚本、专用工具和专用测试，应用非 Docker、非启动器模式不再把仓库根当作生产数据根；长期文档、CI、源码门禁和测试消费者已经改接到 EXE 与 T-LAUNCHER。

- 已完成本机、局域网、端口冲突、显式退出和父进程异常退出产品冒烟；内置 BBDown 1.6.3 与 FFmpeg 7.1.1 从 EXE 已校验资源目录展开，后端和工具路径不依赖系统 Python、BBDown 或 FFmpeg。
- 最终源码树已重新生成 `dist/bili-workspace-launcher-0.7.0.exe` 与 `launcher/current-build.json`，并通过构建器自检、PE amd64、资源摘要、单文件大小和源码门禁复核。
- 正式树交付物 `build_id` 为 `bb73fbe40cab`，大小 83,403,582 字节，SHA-256 为 `4a878e973f92f32947fc6e28ad356a8c4214dad781eff35b4cd2b78fa63430ba`，资源清单 SHA-256 为 `a74452b94d1e6ea62a5d837a0b8d6d999a69e2a1cdb95e187b0ba2b68a5974ba`；构建记录使用 Python 3.11.1、PyInstaller 6.22.0 与 PySide6 6.11.1，并确认执行 EXE 自检。
- 已完成当前树的启动器、受影响项目测试、Ruff、T-DOC 和 `git diff --check`；没有把全量测试或正式认证虚构为本次结果。
- 真实 Docker build/save/inspect 与覆盖故障注入仍未运行；该项保留为产品的显式外部验收，不阻止 Windows 启动器及旧链退役方案关闭。

本方案完成后已完整移入 `archive/docs/plans/`，活动待办和活动方案入口同步退出；真实 Docker 构建与导出继续按用户后续需要单独执行。
