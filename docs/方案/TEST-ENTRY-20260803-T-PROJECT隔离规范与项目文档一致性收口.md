# T-PROJECT 隔离、Docker 非 root、运行资产字段与项目文档一致性收口方案

- 状态：实施中
- 主责：完整实施 T-PROJECT 仓库外隔离、Docker 非 root 边界、Windows 运行资产字段迁移和直接相关文档收口
- 关联待办：[TEST-ENTRY-20260803](../已知问题与待做需求.md)

## 1. 活动真源、授权与范围

当前文档生命周期和活动方案入口由[文档索引](../README.md)承接，活动待办由[已知问题与待做需求](../已知问题与待做需求.md)承接。本方案是 `TEST-ENTRY-20260803` 的唯一活动方案；关联的 `DOC-AUTH-20260806` 已完成双方共享的长期授权、入口和测试安全规则迁移并退出活动区，不承接本方案的实现、验证结果或关闭决定。

用户已授权完整实施当前方案，确定修改范围为：

- T-PROJECT 的 Windows 与 Linux/macOS 入口、隔离 helper、配置同步边界、结构检查、直接测试和调用这些入口的活动 workflow；
- Docker Compose、配置检查器、直接测试和必要运维说明；
- Windows 运行资产构建器、顶层 manifest、准备器、本地状态语义、直接测试和字段/恢复说明；
- 根入口、文档索引、当前恢复手册、测试安全与项目入口、活动待办和本方案的事实同步。

本轮不修改应用业务、API、数据库 schema、第三方二进制 pack、真实配置或运行数据，不创建 tag、GitHub Release 或 GHCR 正式镜像。2026-08-05 的实施与验证是在当时生效的“文件修改不包含命令、验证、删除和关闭”规则下分别授权，相关记录继续作为历史快照保留；后续动作改按当前[项目协作约束](../../AGENTS.md#授权与安全)、本方案范围和实际副作用判断，`DOC-AUTH-20260806` 的实施授权不转授给本方案。

## 2. 已确认决策

### 2.1 T-PROJECT 隔离

[测试安全](../../SoftwareTesting/SAFETY.md)继续作为权威契约，不通过弱化安全说明迁就旧入口。两个规范入口必须：

- 在仓库外测试根下为每次执行新建唯一 `<run-id>/`；
- 根和运行目录分别使用 `.bili-workspace-test-root.json` 与 `.bili-workspace-test-run.json` 证明当前项目、仓库和路径所有权；
- 拒绝无标记既有根、标记冲突、符号链接/重解析点、路径穿越，以及测试根与仓库相同或互相包含；
- 把配置、数据库、下载、运行时、媒体工具、HOME、缓存、临时文件、Python 字节码、pytest basetemp、日志和结果限制在本次运行目录；
- 默认保留运行目录，不提供隐式或失败后自动递归清理；
- 在 `results/result.json` 记录 `passed`、`failed`、`blocked`、`inconclusive` 或 `not_run`；
- 只同步等待本次入口直接启动的子进程，不按名称终止进程，也不启动应用服务、浏览器或容器。

Windows 默认测试根为 `D:\Projects\python\bili_workspace_test`，Linux/macOS 默认根为 `${TMPDIR:-/tmp}/bili_workspace_test`；`BILI_TEST_ROOT` 只改变根位置，不绕过相同的所有权和 containment 校验。

### 2.2 Docker 非 root

需求和设计中的非 root 契约保持不变。Compose 默认用户固定为 `1000:100`，`docker/verify-config.sh` 在解析为数字后拒绝 `PUID=0` 或 `PGID=0`，容器入口再独立拒绝实际 UID 或 GID 为零。受支持的启动脚本必须先通过配置检查；如未来需要 root，必须另开安全产品决策。

### 2.3 运行资产版本语义

应用版本保持 `APP_VERSION=0.7.0`。Windows 运行资产采用独立版本体系，当前为 `runtime_bundle_version=0.5.6`：

- 顶层 `runtime-manifest.json` 提升为 schema 2，新写入只使用 `runtime_bundle_version`；
- 准备器兼容读取 schema 1 的 `bili_workspace_version`，但 schema 2 缺少新字段或仍带旧字段时拒绝；
- 新 `runtime-state.json` 使用 schema 2 和 `runtime_bundle_version`；
- 构建器下一次生成 pack 时在包内元数据写新字段；
- 现有 Python、BBDown 和 FFmpeg pack 不因纯字段改名重建，顶层 manifest 中既有 pack 路径、大小和 SHA-256 保持不变；
- 不把应用改为 0.5.6，不提升为 0.7.1，也不恢复正式发布。

### 2.4 文档职责

- `CHANGELOG.md` 继续承接活动版本历史摘要索引，完整版本快照、Review、问题清单和发布正文由归档承接；
- 根 README 只保留用户可观察摘要，前端实现结构由[设计文档](../设计文档.md)承接；
- 当前恢复手册使用 schema v4 恢复核对，不再把 V0.6.0 发布验收伪装成当前流程；
- [字段契约](../字段契约.md)拥有 `runtime_bundle_version`、schema 兼容与 Docker UID/GID 字段规则；运行资产和运维文档只保留必要操作摘要。

## 3. 实施记录

### 3.1 T-PROJECT 入口与安全边界

已完成文件修改：

- 新增 `tools/t_project_isolation.py`：跨平台创建/验证所有权标记、run-id、固定子目录和原子结果记录；不含删除动作；
- 新增 `scripts/windows/new-test-run.ps1`：在内置 Python 尚未解压前为 Windows 创建隔离运行目录，并在结束时写结果；
- `verify.bat`：不再调用正常启动用 `prepare-runtime.bat`，改为创建隔离运行后调用 `bootstrap-runtime.bat -VerificationRunRoot`；所有环境路径、运行时、媒体工具、日志、字节码和 pytest basetemp 指向本次 run-id，成功或失败均保留目录；pytest 子步骤清除入口注入的产品路径变量，让各测试按自身 fixture 派生数据库和运行目录；批处理保持 UTF-8 无 BOM 与 CRLF；
- `scripts/dev/verify-source.sh`：使用同一 Python helper 建立外部运行目录，隔离配置和临时资产，为每一步保存日志并记录最终状态；pytest 子进程同样清除入口注入的产品路径变量，同时保留仓库外 HOME、临时目录、字节码和 basetemp 隔离；
- `scripts/windows/bootstrap-portable.ps1`：正常启动路径保持原样；仅在显式验证模式下校验双层标记并把 `.runtime`、BBDown 和 FFmpeg 解压到本次运行目录；
- `tools/config_sync.py`：只有 `BILI_VERIFY_RUN_ROOT` 通过所有权校验时才接受 `BILI_VERIFY_ROOT_ENV_PATH`，且目标必须位于该运行目录；验证模式跳过仓库根旧 `config.json` 迁移；
- `tools/verify_source.py`、`tests/test_t_project_isolation.py`、`tests/test_integrated_runtime.py` 和 `tests/test_repository_layout.py`：登记新入口并覆盖所有权、containment、无标记阻断、外部配置写入和默认不清理的静态/单元断言；
- Windows CI 与运行资产构建 workflow 不再预先执行会写仓库实际配置的 `prepare-runtime.bat`，由隔离后的 `verify.bat` 完成验证。

### 3.2 Docker 非 root

已完成文件修改：

- `docker/compose.yaml` 的用户默认值与 `docker/.env.default` 对齐为 `1000:100`；
- `docker/verify-config.sh` 拒绝任一 UID/GID 为零；
- `docker/entrypoint.sh` 在运行应用前拒绝实际 root UID 或 GID，覆盖绕过配置脚本直接调用 Compose 的路径；
- `tests/test_v05_docker.py` 增加 Compose 默认用户和零值拒绝锚点；
- 字段契约、根 README 和 QNAP 部署指南明确非零规则。

### 3.3 运行资产字段迁移

已完成文件修改：

- `tools/build_integrated_runtime.py` 使用 `RUNTIME_BUNDLE_VERSION`，生成 schema 2 顶层清单和新字段包内元数据；
- `vendor/windows/runtime-manifest.json` 只迁移顶层 schema/字段，保留两个既有 pack 的路径、大小和 SHA-256；
- `scripts/windows/bootstrap-portable.ps1` 归一读取 schema 1/2，并只写 schema 2 本地状态；
- `tools/verify_source.py` 和 `tests/test_integrated_runtime.py` 检查 schema 2、新字段、旧字段退出、应用/运行资产版本解耦与既有 pack 身份；
- 字段契约、Windows 运行资产说明、第三方说明和恢复清单同步区分应用版本与运行资产版本。

### 3.4 文档一致性

已完成文件修改：

- `docs/README.md` 消歧 CHANGELOG 活动摘要和归档正文；
- `CHANGELOG.md` 以“未发布”记录本次实现，不创建 0.7.1 或任何正式发布物；
- `README.md` 压缩 V0.7.0 易漂移实现清单，并记录隔离验证与 Docker 非 root 用户边界；
- `docs/运维/备份恢复与V0.4迁移.md` 改为当前 schema v4 恢复核对；
- `SoftwareTesting/SAFETY.md`、`SoftwareTesting/project/README.md` 和 `scripts/README.md` 与实际隔离入口、标记名、结果位置和默认保留语义一致；
- `docs/已知问题与待做需求.md` 与本方案同步进入实施中。

## 4. 安全与兼容边界

- 隔离 helper 只创建和验证目录、写标记与结果，不删除测试根或 run-id；本方案没有列明清理，现有运行证据继续默认保留。未来已确认方案列明的、本任务创建且所有权可验证的精确 run 清理按当前[项目协作约束](../../AGENTS.md#授权与安全)执行，其他清理仍须精确授权。
- Windows 验证目录在运行时准备器执行任何递归替换前完成标记、仓库身份、直接父子和外部路径校验。
- 正常 `start.bat → prepare-runtime.bat` 仍使用仓库忽略的实际本地 `.runtime`、配置和媒体工具路径，不被测试变量默认改变。
- 验证配置同步只读仓库模板，不迁移或写入仓库根的实际 `.env`、`config/runtime.env`、`config/config.json` 或旧 `config.json`。
- 既有 pack 二进制和哈希没有修改；只有 manifest 字段语义改变。任何未来 pack 重建、网络下载或 Artifact 接纳均需另行授权。
- Docker 配置检查仍先验证字段为数字，再执行非零判断，避免把非数字值交给数值比较。

## 5. 验证义务与当前结果

- 测试层级：全量测试；执行本方案已经列明的 T-DOC、T-PROJECT 及直接影响域验证，不提升为正式认证或发布。
- 验证影响域：T-PROJECT 仓库外隔离、配置同步边界、Docker 非 root、Windows 运行资产 schema 1/2 兼容、应用与运行资产版本解耦、文档机械一致性和既有 pack 身份。
- 具体验证项：以下六组计划验证项；实际命令、环境前置条件、逐项状态和证据路径按本轮执行结果记录。

计划验证项：

1. Python 单元测试覆盖隔离根、run-id、所有权标记、containment、无标记既有目录、结果记录和配置写入边界；
2. Windows 静态入口测试覆盖验证模式、双层标记、默认保留、pytest basetemp、schema 1/2 分支和新状态字段；
3. Docker 静态和负向验证覆盖默认 `1000:100`、`PUID=0`、`PGID=0` 与最终 Compose 用户；
4. 运行资产验证覆盖 schema 2 输出、schema 1 兼容、缺失/冲突字段拒绝、应用 0.7.0 与运行资产 0.5.6 解耦，以及既有 pack 哈希不变；
5. T-PROJECT Windows 与 Linux/macOS 真实隔离运行证明全部输出位于本次运行根，仓库实际配置与持久化目录不变；
6. T-DOC、完整 pytest、Ruff、compileall、Node、Windows 运行资产冒烟和 Docker 配置检查。

当前结果（2026-08-05）：用户已授权本方案列明的验证。验证进入可判定阶段后发现并修复两项范围内回归：入口级产品路径变量污染 pytest fixture，导致多个测试共享数据库；`verify.bat` 行尾变为 LF。Windows 与源码入口现只在 pytest 子进程清除这些产品路径变量，仍保留仓库外 HOME、临时目录、字节码和 basetemp；`verify.bat` 已恢复 CRLF。

- `passed`：T-DOC 项目门禁 0 warning，规则夹具 27 项通过；聚焦影响域 40 passed、2 skipped、1 deselected；修复回归集 13 passed、1 skipped；配置同步、compileall、Ruff、排除唯一 Git 节点后的完整 pytest（263 passed、12 skipped、1 deselected）、29 个 `.js/.mjs` 语法检查和 11 个 Node 测试通过。主证据目录为 `D:\Projects\python\bili_workspace_test\20260805T022437Z-8a4c24c77d52`。
- `passed`：Windows 集成 Python、BBDown 与 FFmpeg 在独立运行目录完成解压和冒烟，证据目录为 `D:\Projects\python\bili_workspace_test\20260805T022627Z-e60ef84dd82e`。
- `passed`：Docker Compose 使用模板完成静态解析；隔离 fixture 的合法 `1000:100` 配置通过，`PUID=0`、`PGID=0` 均被拒绝；WSL root 调用容器入口时在启动命令前被拒绝。
- `blocked`：Docker Desktop 客户端存在但 daemon 未运行，无法完成真实容器用户、挂载与入口动态验证；未启动 Docker Desktop。
- `blocked`：WSL 规范入口正确建立 `/tmp/bili_workspace_test/20260805T021529Z-22b5619fe066` 后因缺少 Node.js 记录阻断；WSL Python 同时缺少 pytest，未获安装授权。
- `inconclusive`：Windows pytest 的 12 个跳过项包括 7 个缺少 Playwright 的 UI 文件、3 个 POSIX fixture 和 2 个当前权限不允许创建符号链接的负向测试；其中符号链接和 POSIX 证据原计划由 Linux 入口补齐，但该入口目前被环境前置条件阻断。
- `not_run`：规范 T-PROJECT 中 `tools/verify_source.py` 和根布局测试依赖只读 `git ls-files`；Git 命令仍未单独授权。完整 `verify.bat` 因会触发该 Git 节点而未运行。

因此本轮验证总体为 `inconclusive`，不是 `passed`。文件实施和可运行的非 Git 验证已完成，但在 Git 节点、Linux 依赖和 Docker daemon 证据补齐前，本待办和方案继续保持“实施中”。

## 6. 完成、验收与关闭边界

进入用户验收前必须满足：

- 静态复核不再发现旧字段、旧调用链、root 绕过、仓库内验证输出或文档职责冲突；
- 用户另行授权并完成与风险相称的验证，实际结果写入本节；
- 若验证失败，只在本方案范围内修复，不通过删除证据、弱化 SAFETY、允许 root 或重建 pack 绕过；
- 应用仍报告 0.7.0，运行资产仍报告 0.5.6，数据库仍为 schema v4，正式发布能力仍停止。

本方案主责与完成证明：由上述直接实现差异、静态复核和未来经授权的验证记录共同承接。

关闭时的状态消费者：`docs/已知问题与待做需求.md`、`docs/README.md`、`SoftwareTesting/README.md`、`docs/软件测试.md` 和归档索引。

关联方案、共享文件与对方职责状态：`DOC-AUTH-20260806` 已完成长期规则、根入口、文档索引和测试安全迁移并退出活动区；它没有改变本方案四个实施域、2026-08-05 验证结果或关闭决定。本方案继续独立承接 T-PROJECT 的剩余补证与关闭。

联合只读复核触发条件：`DOC-AUTH-20260806` 修改共享文件后已完成本轮联合只读复核，确认长期规则和职责边界没有改写本方案历史结果；本方案后续补齐验证时仍须按当前候选再执行结果复核。

验收停点：静态复核完成且所有未运行项如实保留后交给用户；本方案仍明确要求用户验收，后续操作按当前项目协作约束和本方案已有授权判断，验收本身不补写未取得的验证结果，也不授权 commit、push、PR 或恢复发布。

关闭边界与未运行验证：用户已于 2026-08-05 授权关闭，但该授权不把 `blocked`、`inconclusive` 或 `not_run` 补成通过；当前不关闭或归档。只有上述必需证据补齐、结果复核完成并取得用户验收后，才按当前项目协作约束使用既有关闭授权退出活动待办、完整移动方案、更新归档索引并验证最终生命周期状态；本次规则迁移不替本方案执行这些动作。
