# Windows 候选构建与验证链路收口方案

- 待办：`WIN-CANDIDATE-20260902`
- 状态：已完成
- 决策基线：[领域语言](../../../CONTEXT.md)与[ADR 0008：仓库跟踪唯一的 Windows 打包快照](../../../docs/adr/0008-track-one-current-windows-launcher.md)
- 测试层级：全量测试；实施候选必须运行 T-PROJECT full、受影响的 T-LAUNCHER、T-DOC 和精确差异检查，任何必需阶段被跳过均不算通过。
- 验证影响域：当前非浏览器 Python 行为、Node 与 Playwright 浏览器行为、Windows amd64 单文件候选的资源准备与自检、全新仓库外临时数据根启动、候选与正式快照的身份和入口、相关 CI 及活动文档。
- 具体验证项：复现并修复当前 `product-validation`、T-PROJECT Playwright 和 Windows launcher candidate 三个失败路径；执行项目完整自检、启动器逻辑与 lint、临时候选构建及 `--self-check`，再用任务自有临时数据根验证本机模式、schema v5 和页面入口，最后执行 T-DOC、`git diff --check` 与工作区差异复核。

## 一、目标与完成后的可观察结果

本任务补上 2026-08-15 之后源码改动缺失的 Windows 单文件候选证明，但不替用户决定何时生成新的 Windows 打包快照。完成后应具备以下结果：

1. 修改会被 Windows 启动器内嵌的源码或构建输入后，任务结束前有一个明确、安全且不晋升的 Windows 候选构建入口。
2. 候选能够生成单文件 EXE、通过资源和依赖自检，并在全新仓库外临时数据根中启动当前 schema v5 后端和页面入口。
3. 候选位于忽略目录，不替换 `dist/bili-workspace-launcher-0.7.0.exe` 或 `launcher/current-build.json`，不进入 Git，也不上传为 CI Artifact。
4. Windows 打包快照只由维护者明确触发现有正式构建/晋升流程；普通源码变更不强制产生或提交约 83 MiB 的正式 EXE。
5. 当前源码的非浏览器 Python、Node、Playwright 和启动器候选验证均恢复为可判定通过；不得用重试、固定等待、跳过或降低断言掩盖失败。

## 二、已确认决策

- `main` 承接最新源码，`dist` 承接最近一次由维护者人工确认的 Windows 打包快照；快照可以落后于 `main`。
- 受影响任务必须生成 Windows 候选构建并完成自检，但候选不是打包快照，不替换 `dist`、不进入仓库且不上传。
- 当前收口范围包括公开 CI 在 `HEAD` 上标红的非浏览器 Python、Playwright 和启动器候选三个路径，不能只修启动器构建。
- 候选除 `--self-check` 外，还必须使用全新的仓库外临时数据根完成本机模式启动验证；不使用真实网站账号、Bilibili 登录、Cookie、数据库、媒体或下载任务。
- 本方案不晋升新的 Windows 打包快照。候选验证结果交给用户，是否以及何时正式打包另行决定。
- 正式打包快照只能从构建前干净且已提交的 Git `HEAD` 生成，并在构建记录中保存完整源码 commit；提交前的工作树仍可生成不晋升的候选用于验证。
- Windows 提供两个职责明确的脚本入口，但共用一套底层构建实现：新增候选验证脚本，现有 `build-launcher.bat` 保留为维护者主动运行的正式快照脚本。
- 本地权威入口全部通过即可关闭本方案，远端 CI 未运行时必须明确记录；相关 hosted 路径实际变绿是以后晋升正式打包快照的前置，而不是本方案关闭条件。

## 三、当前证据与差距

| 当前事实 | 证据 | 必须收口的差距 |
| --- | --- | --- |
| 跟踪的 Windows 打包快照构建于 2026-08-15，最后随提交 `879b35d` 更新，内嵌应用只支持 schema v4 | `launcher/current-build.json`、Git 历史中的 `app/constants.py` | 当前 `main` 已是 schema v5 且包含 8 月 31 日功能，不能用旧快照证明当前源码可打包运行 |
| 8 月 30 日架构方案明确把启动器打包列为未运行，8 月 31 日功能方案只完成 T-PROJECT full 和真实只读 Bilibili 烟雾 | 对应归档方案的实施结果 | 将“启动器源码未改”误当成“不影响内嵌应用”，遗漏了 app/web 变化后的候选 EXE 证明 |
| 最新公开 launcher workflow 在 `Build and self-check Windows amd64 candidate` 失败，没有上传候选 | GitHub Actions run `33361886775` | 必须在现有固定资源和失败关闭边界内复现根因，不得把源码测试冒充打包成功 |
| 同一 `HEAD` 的 `product-validation` 和 T-PROJECT Playwright 阶段也失败，而本地归档结果曾记录通过 | GitHub Actions run `33361886773`、UP-DOWNLOAD 归档结果 | 必须区分产品回归、测试隔离和 hosted runner 差异并修复真实根因 |
| `scripts/windows/build-launcher.bat` 默认直接写正式 `dist` 并更新规范构建记录 | 当前批处理与 `tools/build_launcher.py` | 日常候选验证缺少不碰正式快照的清晰、安全入口 |
| launcher workflow 每次成功后上传保留 5 天的约 83 MiB 候选 | `.github/workflows/launcher.yml` | 新决策要求普通候选不上传；CI 只保留可判定结果和必要日志 |
| `launcher/current-build.json` 记录 EXE 与资源身份，但没有可直接定位源码提交或源码树的字段 | 当前 schema 1 构建记录 | 已裁决正式快照只从干净、已提交的 `HEAD` 生成，并补充完整源码 commit |

## 四、实施范围

### 4.1 复现并修复当前失败

1. 使用各 Registry 的规范入口分别复现非浏览器 Python、Playwright 和 Windows 候选构建失败，保留首个可判定根因；不从 GitHub 私有日志或真实运行现场复制数据进仓库。
2. 根因若属于产品代码、测试隔离、构建输入、固定资源获取或 hosted runner 接线，只修改拥有该行为的唯一实现和相应测试。
3. 偶发、环境或依赖问题必须准确记录为 `failed`、`blocked` 或 `inconclusive`；不增加无依据重试、固定等待、永久跳过或宽松断言。

### 4.2 建立安全的候选验证入口

1. 候选入口复用 `tools.build_launcher` 的资源哈希、FFmpeg 来源证据、BBDown/FFmpeg 工具冒烟、PyInstaller、PE amd64、100 MiB 停止线和 EXE 自检，不复制第二套打包实现。
2. 新增独立的 `validate-launcher-candidate.bat` 作为日常候选入口；它与正式 `build-launcher.bat` 调用同一权威 Python 实现，但自身不得提供晋升开关或把额外参数透传成正式输出路径。
3. 候选的 EXE、构建记录、资源 staging、PyInstaller 工作区和临时数据根必须位于任务拥有的唯一忽略路径；不得覆盖既有 `build/` 产物或其他任务目录。
4. 候选入口不得引用正式 `dist` 或规范 `launcher/current-build.json`，也不得执行 commit、push、Release、镜像发布或 Artifact 上传。
5. 自检通过后，只启动本次候选及其直接拥有的后端，在回环本机模式下核对健康响应、候选 `build_id`、schema v5 初始化和页面入口；随后只终止自有进程并按所有权精确清理本次临时数据根。
6. 候选 EXE 是否在交接前保留供人工查看，由入口采用显式 `--keep-candidate` 控制；默认在结果采集后精确清理，不扫描或删除其他历史构建目录。

### 4.3 调整测试选择与 CI

1. T-LAUNCHER 的触发条件明确覆盖实际内嵌输入：`app/`、`web/`、`LICENSES/`、运行依赖锁、启动器使用的 Docker 文件、launcher 源码/spec/依赖/notice，以及拥有这些输入的构建工具和 workflow。
2. 本地候选入口和 Windows launcher workflow 调用同一权威构建逻辑；workflow 不上传候选 EXE，只凭退出状态报告打包和自检结果。
3. 修复现有 launcher workflow 后仍保留 Windows amd64、Python 3.11、固定依赖与固定资源的失败关闭，不改为 Linux 模拟或纯静态检查。
4. 非浏览器 Python 和 Playwright 继续由 T-PROJECT 的既有消费者拥有；不得为了让单个 CI job 变绿而重复或拆出等价 Registry。
5. 本方案以本地权威入口的完整通过结果作为关闭证据；没有经授权 push 时将 hosted CI 记录为未运行。以后晋升正式快照前，相关 hosted 路径必须已对待晋升 commit 实际变绿。

### 4.4 建立打包快照的源码身份

1. 正式打包快照的构建记录必须能够定位或验证被内嵌的精确源码，而不只记录构建时间和 EXE 哈希。
2. 候选记录使用同一身份生成逻辑，但位于 `build/`，不更新当前正式快照记录。
3. 身份必须覆盖构建器实际复制的仓库输入，排除时间、临时路径、EXE 和构建记录本身，避免循环身份。
4. 正式快照构建前必须确认工作树干净、`HEAD` 已提交，并把完整 commit 写入构建记录；候选记录使用相同字段记录其构建时 `HEAD`，但候选可另行标明工作树不干净，不能冒充可恢复的正式快照。

### 4.5 同步当前文档

- 把需求、设计、字段契约、README、脚本入口、T-LAUNCHER 和运维恢复说明中的“当前 EXE”区分为“最新源码”与“Windows 打包快照”。
- 明确候选验证不是正式发布、正式认证或打包快照晋升，也不保证 `dist` 与 `main` 同步。
- 当前 `dist` 和规范构建记录保持逐字节不变；在下一次人工晋升前，不把 schema v4 快照描述为当前 schema v5 可执行物。

## 五、授权边界与排除项

2026-09-02，用户在完成 Review 裁决后明确授权按修订方案实施，随后又明确授权 T-PROJECT full、固定 BBDown/FFmpeg/PyInstaller 工具进程、缓存缺失时的固定公开资源下载、Windows 候选构建、候选 EXE 自检及仓库外全新临时数据根产品启动。

本次授权不包含且没有执行：commit、push、PR、远端 workflow、正式快照晋升、Docker 构建/导出、真实数据、真实 Bilibili 登录或下载。

明确不做：不修改应用版本、不创建 tag/Release/GHCR 镜像、不更新 `dist` 或规范 `launcher/current-build.json`、不恢复旧便携运行链、不接触现有真实数据根、不清理本任务无法证明所有权的历史 `build/` 内容。

## 六、建议实施顺序

1. 先用聚焦命令复现公开 CI 的 Python 与 Playwright 失败，确认是否为产品回归、测试状态泄漏或 hosted runner 接线问题。
2. 用新的任务唯一候选路径复现 launcher workflow 的构建失败；在资源准备、工具冒烟、PyInstaller 或自检中定位首个根因。
3. 修复单一根因及相应回归，再建立不触碰正式快照的候选验证入口。
4. 补充正式快照源码身份及候选/晋升模式的构建工具测试，不更新现有规范构建记录。
5. 调整 T-LAUNCHER、CI 与当前活动文档，移除普通候选 Artifact 上传。
6. 运行聚焦验证；取得单独授权后运行 T-PROJECT full、受影响 T-LAUNCHER 候选构建、自检和全新临时数据根启动。
7. 完成 T-DOC、`git diff --check` 和最终差异复核，确认 `dist` 与 `launcher/current-build.json` 未变化且没有候选进入 Git。

## 七、完成条件

只有同时满足以下条件，方案才可退出活动区：

- 三个当前失败路径均有可复现根因和不掩盖失败的修复，必要的 Python、Node、Playwright 和启动器测试通过；
- 当前源码生成的 Windows 候选构建完成资源核验、单文件构建与 `--self-check`，并在全新临时数据根中以 schema v5 正常启动；
- 候选未替换正式快照、未进入 Git、未上传，任务自有运行数据和临时进程已精确清理；
- 后续人工打包能够生成可核对的源码身份，当前文档准确区分源码、候选构建和打包快照；
- T-DOC 与 `git diff --check` 通过，用户已获得实际运行项、结果和未覆盖项；
- 本地权威入口全部通过；远端 CI 若未运行已如实标注，且文档已把相关 hosted 路径实际变绿列为未来正式快照晋升前置。

## 八、停止条件

出现以下任一情况时停止并请求授权或新决定：

- 根因修复需要改变既有产品行为、认证/权限、数据迁移、下载合同或支持平台；
- 固定资源身份或许可证材料必须更换，而不是修复现有获取/验证接线；
- 需要安装或下载、访问认证日志、启动未授权产品/工具进程、使用真实数据或 Docker；
- 候选流程无法在不覆盖正式 `dist`、规范构建记录或所有权不明的历史产物时运行；
- 需要 commit、push、PR、修改远端设置、晋升正式打包快照或发布；
- 当前工作区出现与目标文件重叠且无法安全合并的既有修改。

## 九、保存后 Review 结论

本次 Review 对照了构建器、资源准备器、启动器隐藏 CLI、Windows workflow、T-LAUNCHER、T-PROJECT、活动运维文档和构建记录消费者。没有发现需要扩大到 Docker、真实 Bilibili 数据或正式发布的理由；发现以下实现约束：

1. 当前 `build-launcher.bat` 没有区分“验证候选”和“晋升快照”：不传参数就直接写 `dist` 和规范构建记录。只靠维护者记住一组长参数容易误晋升，必须提供语义明确的安全入口。
2. 当前 `build_id` 已覆盖实际内嵌资源与启动器输入，适合核对内容；但 `current-build.json` 没有源码提交字段，单凭 12 位内容摘要不能从 Git 历史直接定位构建来源。正式快照仍需另一个可恢复的源码定位身份。
3. 当前 EXE 只有隐藏的 `--self-check` 和内部 `--run-backend`；前者不初始化数据库或启动 HTTP 服务，后者依赖启动器生成的受保护会话协议。要自动证明全新数据根运行行为，应新增隐藏的验证模式或等价测试工具，由它创建、启动、探测并停止自有进程；不把该入口做成正常用户功能。
4. workflow 中 Ubuntu 到 Windows 的 FFmpeg 固定构建输入传递仍是两个 job 之间的内部依赖，不等同于上传候选 EXE 供下载。本方案只取消约 83 MiB 的 launcher validation Artifact；若后续要连这类内部传递也取消，必须重新设计 job 边界，不在本次顺带处理。
5. 三个公开 CI 失败发生在 hosted runner，而当前工作树只能先通过本地权威入口复现和修复。是否必须以远端实际变绿作为本方案关闭证据，会改变是否需要 commit、push 和等待 workflow，不能由实施者代替用户决定。

全新数据根冒烟、候选唯一目录、默认精确清理、保留候选的显式开关和 FFmpeg 已验证缓存复用均可按既有安全边界确定，不需要额外产品决策。Review 提出的三项用户裁决均已完成：

1. **正式快照源码身份（已裁决：干净 Git `HEAD`）**：正式快照只能从构建前干净、已提交的 `HEAD` 生成并记录完整 commit；候选仍可验证未提交工作树。正式打包前需要先提交源码，二进制和构建记录随后另行提交。
2. **脚本入口形状（已裁决：两个脚本、一个实现）**：新增 `validate-launcher-candidate.bat`，只在唯一临时目录构建、验证并默认清理候选；保留 `build-launcher.bat` 作为维护者主动运行的正式快照入口。两者共用同一权威 Python 构建逻辑，均不自动 commit、push 或上传。
3. **远端 CI 关闭条件（已裁决：本地关闭、晋升前远端验证）**：本地权威入口完整通过即可关闭本方案；未获授权 push 时如实记录远端未运行。相关 hosted 路径对待晋升 commit 实际变绿，是以后正式快照晋升的前置。

## 十、实施结果（2026-09-02）

1. `product-validation` 的六个失败来自测试基线没有把 `BILI_USERDATA_DIR` 指向 pytest 临时目录，导致 hosted runner 尝试创建 `/data/userdata`；测试基线现已补齐隔离路径。
2. Playwright 失败来自 Chromium 单例 Unix socket 路径超过平台上限；workflow 的 T-PROJECT 根已缩短为 `/tmp/bw`，隔离 run、失败诊断 Artifact 与精确清理语义保持不变。
3. Windows launcher 失败来自 Linux 证据中的 LF `ffmpeg-builder.Dockerfile` 与 Windows checkout 的 CRLF 配方身份不一致；`.gitattributes` 已固定 `*.Dockerfile text eol=lf`，并由启动器测试锁定。
4. 实际候选自检还发现 PyInstaller 会从调用进程的 `PATH` 误收集同名但导出契约不兼容的外部 `icuuc.dll`，导致冻结后的 `PySide6.QtWidgets` 加载失败；构建器现只向 PyInstaller 暴露当前 Python 和 Windows 系统 DLL 目录，并隔离外部 Python、Qt 与 QML 路径，回归测试锁定该边界。
5. 已新增安全候选脚本、唯一候选目录及所有权标记、schema 2 源码身份、正式快照干净 `HEAD` 门禁、隐藏运行时冒烟、全新数据根 schema/页面检查，以及 CI 不上传候选 EXE 的接线；`dist` 与 schema 1 规范记录保持不变。
6. 经授权运行 T-PROJECT full 并通过，包含不可跳过的 Playwright 阶段；实际 Windows amd64 单文件候选完成固定资源与工具核验、PyInstaller 构建、EXE 自检、仓库外全新数据根后端启动、schema v5 和首页探针，验证通过后候选目录自动精确清理。
7. 启动器聚焦测试、Ruff、批处理 CRLF 完整性、T-DOC、T-ARCHIVE 与 `git diff --check` 均通过；两份失败诊断候选在核对所有权标记后精确清理，没有候选、运行数据或任务自有临时进程残留。
8. 远端 workflow、正式快照晋升、commit、push、真实数据与真实 Bilibili 操作均未执行；相关 hosted 路径对待晋升 commit 实际变绿，仍是以后正式快照晋升的前置。
