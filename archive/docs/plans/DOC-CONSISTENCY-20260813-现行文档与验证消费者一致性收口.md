# DOC-CONSISTENCY-20260813 现行文档与验证消费者一致性收口方案

- 状态：已完成
- 形成日期：2026-08-13
- 审计方式：全量文档一致性审计
- 方案自审：2 轮
- 施工后反哺报告：不生成
- 对应待办：DOC-CONSISTENCY-20260813
- 测试层级：普通验证；不自动提升为全量测试或正式认证
- 验证影响域：安全报告入口、T-PROJECT 浏览器与退出职责、Actions 缓存、T-DOCKER 触发、历史 CI 条件、Windows 迁移、CHANGELOG、Docker 动态结果、字段数值所有权及生命周期
- 具体验证项：按第 7 节执行静态候选检查、隔离的聚焦 Python 回归、Ruff、文档规则夹具、目标 T-DOC 和经单独授权后的安全设置复核

本方案只冻结已经完成审计并经用户确认的处置，不构成实施授权。保存方案不修改下列实施文件、不运行测试、不启用 GitHub 设置，也不授权 commit、push、PR、发布、安装、产品进程、真实数据、全量测试或正式认证。

## 1. 目标与完成状态

本方案收口现行文档与直接验证消费者之间的十项偏差：

1. 安全策略必须提供真实可用的私密漏洞报告入口，并准确说明当前维护对象；
2. T-PROJECT 的 CI 消费者只能复用既有浏览器，不再自行安装 Chromium；
3. 已由 Windows EXE 和 T-LAUNCHER 替代的“集成运行资产阶段”退出 T-PROJECT；
4. 活动 workflows 不再隐式持久写入 GitHub Actions 依赖或构建缓存；
5. T-DOCKER 的 affected-only 输入与 PR 路径触发完整覆盖实际 Docker 构建上下文；
6. 当前 CI 不再按 V0.6/V0.7 历史分支名选择验证作业；
7. 备份恢复手册准确区分 Docker/NAS 兼容迁移和 Windows EXE 手工恢复；
8. CHANGELOG 未发布区只描述当前净状态，不保留已被替代的施工中间事实；
9. 当前 Docker 手册不保存一次性动态验证结果；
10. 设计文档只保留机制和数据流，易漂移数值继续由字段契约唯一承接。

技术完成要求是：十项偏差全部按本方案收口，确定的静态和普通验证通过，GitHub 私密漏洞报告设置经单独授权后实际启用并得到公开只读复核，活动文档与生命周期入口一致。

本方案不把普通验证写成正式认证，不要求实际触发 GitHub Actions，不恢复任何正式发布能力。

## 2. 审计范围

### 2.1 活动文档精确集合

本轮完整读取并完成“事实／契约”和“职责／删减”两轮审阅的活动 Markdown 共 39 份。

根级文档：

1. AGENTS.md
2. README.md
3. CONTEXT.md
4. CHANGELOG.md
5. SECURITY.md
6. THIRD_PARTY_NOTICES.md

核心与条件文档：

7. docs/README.md
8. docs/需求文档.md
9. docs/设计文档.md
10. docs/字段契约.md
11. docs/已知问题与待做需求.md
12. docs/软件测试.md

架构决策：

13. docs/adr/0001-current-facts-by-type.md
14. docs/adr/0002-source-push-does-not-publish.md
15. docs/adr/0003-windows-launcher-keeps-lan-server-mode.md
16. docs/adr/0004-launcher-builds-downstream-artifacts-only.md
17. docs/adr/0005-runtime-data-must-live-outside-the-repository.md
18. docs/adr/0006-launcher-control-root-follows-the-executable.md
19. docs/adr/0007-launcher-exports-amd64-docker-images.md
20. docs/adr/0008-track-one-current-windows-launcher.md
21. docs/adr/0009-windows-exe-replaces-the-portable-runtime-chain.md
22. docs/adr/0010-data-root-owns-network-and-security-settings.md
23. docs/adr/0011-launcher-embeds-bbdown-and-ffmpeg.md
24. docs/adr/0012-repository-uses-one-python-311-baseline.md

运维文档：

25. docs/运维/README.md
26. docs/运维/Docker镜像打包与离线交付.md
27. docs/运维/域名与反向代理配置.md
28. docs/运维/备份恢复与V0.4迁移.md
29. docs/运维/发布与回滚流程.md
30. docs/运维/源文件与恢复清单.md

测试治理：

31. SoftwareTesting/README.md
32. SoftwareTesting/PROTOCOL.md
33. SoftwareTesting/SAFETY.md
34. SoftwareTesting/doc_consistency/README.md
35. SoftwareTesting/docker/README.md
36. SoftwareTesting/launcher/README.md
37. SoftwareTesting/project/README.md

其他活动说明：

38. launcher/RELINKING.md
39. scripts/README.md

### 2.2 直接证据与消费者

只沿活动声明读取一层直接依赖，主要包括：

- 应用版本、配置、schema、运行时、迁移、索引、任务日志、搜索、认证、媒体和状态实现；
- app/defaults、Dockerfile、Compose、默认环境模板、launcher/current-build.json；
- 三个活动 GitHub Actions workflow；
- T-PROJECT、T-DOCKER、T-LAUNCHER 的直接 helper、选择器和核心静态断言；
- 当前 Windows 启动器后端环境、旧路径禁用和相关隔离测试；
- Git 跟踪清单与工作树只读状态；
- GitHub 私密漏洞报告公开 API、GitHub 托管 runner 官方软件清单、QNAP 官方规格和导入说明、BBDown 官方仓库状态。

测试设计采用“声明绑定模式”：只审查本轮文档声明直接要求的 suite、CI、测试安全和核心断言，不扩张为 Registry 全局测试审计。

### 2.3 排除项

- archive 下历史正文的内容重审；归档只用于当前承接和历史结果归宿证明；
- 未被活动声明锚定的产品代码和测试；
- 真实配置、Cookie、Token、数据库、媒体、用户浏览器 profile 和运行现场；
- 二进制候选重建、Docker 实际构建、浏览器运行、产品启动、全量测试和正式认证；
- commit、push、PR、tag、Release、GHCR、部署和其他远端写入；
- 施工后反哺报告、额外检查报告、profile、manifest 或执行日志文档。

## 3. 权威与已确认决定

### 3.1 当前职责链

- AGENTS.md：授权与安全边界；
- docs/需求文档.md：用户可观察行为与支持边界；
- docs/设计文档.md：实现结构、调用链和数据流；
- docs/字段契约.md：跨边界字段、默认值和易漂移常量；
- docs/软件测试.md、SoftwareTesting/PROTOCOL.md、SoftwareTesting/SAFETY.md 和 suite README：测试身份、层级、安全和执行契约；
- workflow、helper 和测试断言：上述权威的直接消费者；
- CHANGELOG.md：当前未发布变更和历史版本摘要；
- 运维手册：当前可执行操作，不承接一次性动态结果。

### 3.2 用户决定

SECURITY.md 当前承诺使用仓库私密安全报告渠道，但 GitHub 公开 API 在审计时返回 enabled=false。用户已确认采用推荐方向：

- 后续另行明确授权后启用 GitHub Private Vulnerability Reporting；
- 设置启用并公开复核为 enabled=true 后，SECURITY.md 才写入精确私密报告入口；
- 当前维护对象改为 main 中的当前源码，冻结的 V0.7.0 Release 和 GHCR 历史产物不冒充后续安全修复；
- 本次“只保存方案”不授权启用设置。

其余九项均可由当前权威和直接证据唯一裁决，不需要新增产品语义决定。

## 4. 覆盖矩阵

| 活动文档 | 审阅结果 | 发现或残余 |
| --- | --- | --- |
| AGENTS.md | 已覆盖 | 无内容施工项；拥有授权边界 |
| README.md | 已覆盖 | 无施工项 |
| CONTEXT.md | 已覆盖 | 无施工项 |
| CHANGELOG.md | 已覆盖，存在偏差 | F-08 |
| SECURITY.md | 已覆盖，存在偏差 | F-01 |
| THIRD_PARTY_NOTICES.md | 已覆盖 | 当前 BBDown 与 FFmpeg 来源一致 |
| docs/README.md | 已覆盖 | 无内容施工项；保存与关闭生命周期消费者 |
| docs/需求文档.md | 已覆盖 | 无施工项 |
| docs/设计文档.md | 已覆盖，存在重复所有权 | F-10 |
| docs/字段契约.md | 已覆盖 | 易漂移字段唯一所有者，无施工项 |
| docs/已知问题与待做需求.md | 已覆盖 | 仅承接本方案待办生命周期 |
| docs/软件测试.md | 已覆盖 | Registry 身份一致 |
| docs/adr/0001-current-facts-by-type.md | 已覆盖 | 无施工项 |
| docs/adr/0002-source-push-does-not-publish.md | 已覆盖 | F-06 的裁决依据 |
| docs/adr/0003-windows-launcher-keeps-lan-server-mode.md | 已覆盖 | 无施工项 |
| docs/adr/0004-launcher-builds-downstream-artifacts-only.md | 已覆盖 | 无施工项 |
| docs/adr/0005-runtime-data-must-live-outside-the-repository.md | 已覆盖 | 无施工项 |
| docs/adr/0006-launcher-control-root-follows-the-executable.md | 已覆盖 | 无施工项 |
| docs/adr/0007-launcher-exports-amd64-docker-images.md | 已覆盖 | 无施工项 |
| docs/adr/0008-track-one-current-windows-launcher.md | 已覆盖 | 无施工项 |
| docs/adr/0009-windows-exe-replaces-the-portable-runtime-chain.md | 已覆盖 | F-03、F-07 的裁决依据 |
| docs/adr/0010-data-root-owns-network-and-security-settings.md | 已覆盖 | 无施工项 |
| docs/adr/0011-launcher-embeds-bbdown-and-ffmpeg.md | 已覆盖 | 无施工项 |
| docs/adr/0012-repository-uses-one-python-311-baseline.md | 已覆盖 | 无施工项 |
| docs/运维/README.md | 已覆盖 | 无施工项 |
| docs/运维/Docker镜像打包与离线交付.md | 已覆盖，存在历史结果滞留 | F-09 |
| docs/运维/域名与反向代理配置.md | 已覆盖 | 外部说明已核对，无施工项 |
| docs/运维/备份恢复与V0.4迁移.md | 已覆盖，存在事实偏差 | F-07 |
| docs/运维/发布与回滚流程.md | 已覆盖 | F-02、F-04、F-06 的权威上下文，无施工项 |
| docs/运维/源文件与恢复清单.md | 已覆盖 | 无施工项 |
| SoftwareTesting/README.md | 已覆盖 | 无施工项 |
| SoftwareTesting/PROTOCOL.md | 已覆盖，存在退出职责 | F-03 |
| SoftwareTesting/SAFETY.md | 已覆盖，存在退出职责 | F-03；F-02、F-04 的权威依据 |
| SoftwareTesting/doc_consistency/README.md | 已覆盖 | 无施工项 |
| SoftwareTesting/docker/README.md | 已覆盖，存在输入缺口 | F-05 |
| SoftwareTesting/launcher/README.md | 已覆盖 | F-03、F-07 的承接依据，无施工项 |
| SoftwareTesting/project/README.md | 已覆盖 | F-02 的权威依据，本文件无施工项 |
| launcher/RELINKING.md | 已覆盖 | 无施工项 |
| scripts/README.md | 已覆盖 | 无施工项 |

覆盖集合、发现集合和下文确定切片使用同一组 F-01 至 F-10，不存在未映射发现。

## 5. 冻结发现与处置

### F-01：私密漏洞报告入口不可用

- 证据：SECURITY.md 声称使用仓库私密安全报告渠道；审计时 GitHub 公开 API 返回 enabled=false。项目同时停止未来正式发布，现有“V0.7.x”维护表述没有说明 main 与冻结发布物的关系。
- 影响：报告者无法按文档进入承诺渠道，冻结历史产物也可能被误解为继续接收后续修复。
- 确定处置：把 GitHub 设置作为单独外部写入阶段；启用并复核后，SECURITY.md 链接仓库 security/advisories/new，并明确当前维护对象和冻结历史产物边界。
- 停止条件：没有明确外部写入授权、认证不可用、设置状态不能公开复核或仓库身份变化时，不修改 SECURITY.md 的可用性承诺，方案保持活动。

### F-02：CI 浏览器供给违反 T-PROJECT 契约

- 证据：SoftwareTesting/SAFETY.md、SoftwareTesting/project/README.md 和当前运维流程都规定只复用既有浏览器；.github/workflows/ci.yml 仍执行 Playwright Chromium 安装并解析安装目录；tests/_v070_frontend_architecture_original.py 保护该目录形态。
- 影响：CI 消费者扩大联网、安装和运行资产副作用，并与本地 T-PROJECT 的 blocked 语义分叉。
- 确定处置：删除安装与 headless-shell 解析步骤，让 scripts/dev/run-playwright-phase.sh 和 tools/playwright_runtime.py 探测 GitHub 托管 runner 已有 Chrome、Edge 或 Chromium；缺失时保持 blocked。
- 回归处置：把旧断言改为禁止安装和安装目录绑定，并继续要求唯一浏览器阶段、隔离 helper 与证据上传存在。

### F-03：T-PROJECT 仍声明已退役运行资产阶段

- 证据：SoftwareTesting/PROTOCOL.md 仍要求“集成运行资产阶段”，SoftwareTesting/SAFETY.md 仍把 BBDown 和 FFmpeg 列为 T-PROJECT 子进程；当前项目入口、pyproject 选择、源码脚本和 ADR 0009 已把 Windows 集成资产职责交给 T-LAUNCHER。
- 影响：全量测试定义包含没有当前入口的阶段，并可能诱导恢复已经退役的便携运行链。
- 确定处置：从 Protocol 删除该阶段，从 Safety 的 T-PROJECT 进程清单删除 BBDown 和 FFmpeg；不改变 T-LAUNCHER。

### F-04：workflows 隐式持久写入 Actions 缓存

- 证据：AGENTS.md 和 SoftwareTesting/SAFETY.md 要求外部写入另行授权；ci.yml 和 launcher.yml 使用 setup-python 的 pip cache，docker-image.yml 使用 type=gha 的 Buildx cache。短期验证 artifact 已由当前设计显式允许，依赖／构建缓存没有同等声明。
- 影响：普通 push 或 PR 会在验证之外改变远端缓存状态，且 SoftwareTesting/docker/README.md 所称“临时 runner 生命周期”不成立。
- 确定处置：删除 ci.yml 与 launcher.yml 的 cache、cache-dependency-path；删除 docker-image.yml 的 cache-from、cache-to。保留具有明确保留期的失败日志、Playwright、FFmpeg 和启动器验证 artifact。
- 回归处置：增加活动 workflows 中不得出现未声明持久缓存配置的静态断言。

### F-05：T-DOCKER affected-only 触发输入不完整

- 证据：.dockerignore 会改变根构建上下文，ci.yml 是现有单架构 Docker 消费者；SoftwareTesting/docker/README.md 没有精确列明两者，docker-image.yml 路径过滤也没有覆盖它们，且专用多架构验证没有 pull_request 路径触发。
- 影响：候选在合并前或相关输入改变时可能缺少多架构 Docker 证据。
- 确定处置：suite README 显式加入 .dockerignore 和相关 workflow；docker-image.yml 为 push main 与 pull_request 使用同一精确 paths，补入 .dockerignore 和 .github/workflows/ci.yml，继续保持 contents: read、push: false、无 GHCR 登录和无发布输入。
- 回归处置：tests/test_v070_release.py 断言输入、PR 触发与不发布边界。

### F-06：当前 CI 保留历史分支选择器

- 证据：ci.yml 的 product-validation、windows-validation 和 docker-validation 仍列出 release/v0.7.0、两个 agent/v060 分支和 feature/ui-v0.6.2；tests/test_v060_release.py 还要求其中一个历史分支存在。
- 影响：历史项目阶段成为当前自动化契约，普通 PR 的选择含义不透明。
- 确定处置：三个作业只保留 workflow_dispatch 与 main 条件。普通 PR 的产品 pytest 已由通用 Python 作业承接；Windows 与 Docker 的 affected-only PR 验证分别由专用 workflow 路径触发承接。
- 回归处置：删除历史分支正向断言，改为禁止活动 workflow 出现这些分支名。

### F-07：Windows 迁移说明与实现相反

- 证据：app/state.py 只在 docker/nas 调用旧数据库迁移；索引和任务日志兼容迁移受 BILI_DISABLE_LEGACY_MIGRATION 控制；Windows 启动器固定设置该变量为 1，并有测试证明旧数据库和索引不会移动。migrate_legacy_json 没有生产调用。当前手册却泛称自动迁移，并称 .runtime 会重新生成。
- 影响：Windows 用户可能把旧数据放入不会被扫描的位置，或等待已经退役的运行链重新出现。
- 确定处置：重写第 7、8 节，分别说明 Docker/NAS 的目标不存在时兼容迁移和 Windows EXE 的手工复制；给出 config、userdata、downloads、旧索引／日志、BBDown.data 的目标位置；要求停止服务、保留原副本、不覆盖现有目标；明确 .runtime、Portable Python 和 BBDown_portable 不复制也不重新生成。
- 产品边界：不修改任何迁移代码或数据。

### F-08：CHANGELOG 未发布区包含被替代的中间事实

- 证据：未发布区仍写 T-DOC .runtime 排除、imageio-ffmpeg wheel、FFmpeg v7.1、Windows runtime manifest schema 2 和 runtime_bundle_version=0.5.7；当前 T-DOC 已同步标准资产，Windows EXE 使用 FFmpeg 7.1.1 官方签名源码，旧便携运行资产已经退出。
- 影响：版本摘要与当前净状态相互矛盾，历史中间步骤继续被当作活动事实维护。
- 确定处置：合并和改写相关 bullet，保留 T-DOC 标准化、T-DOCKER、现行 FFmpeg 来源和 Windows EXE 当前事实；删除 .runtime、imageio wheel 和旧 runtime manifest 中间描述。已发布版本段不改写。

### F-09：当前 Docker 手册保存一次性验证结果

- 证据：手册第 8 节保存 2026-08-06 TS-453Bmini 动态结果；完整历史结果已由 archive/docs/plans/DOCKER-QNAP-20260806-QNAP镜像构建验证与私有交付方案.md 和归档索引承接。
- 影响：活动手册同时承担稳定操作和日期结果，后续候选容易沿用旧证据。
- 确定处置：删除“已验证基线”结果段，只把“每个新包都要产生候选专属验证与校验和，旧结果不可复用”并入当前打包／复载规则；不改写归档正文。

### F-10：设计文档重复字段所有权

- 证据：设计文档重复维护 WBI 与搜索缓存秒数、会话天数／触碰间隔／上限、任务保留天数／数量和备份份数；字段契约已经是这些值的唯一当前真源。
- 影响：机制与数值在两处共同维护，常量变化时容易漂移。
- 确定处置：设计文档保留缓存键、失效、淘汰顺序、任务清理流程和迁移事务；删除重复字面数值并链接字段契约。需求文档中的用户可观察上限和字段契约中的规范值不删除。

## 6. 确定实施切片

### 6.1 安全报告切片

外部状态：

- GitHub 仓库 kachekakaka/bili_workspace 的 Private Vulnerability Reporting 设置。

文件：

- SECURITY.md

顺序：

1. 在实施开始前再次公开读取设置状态；
2. 只有用户明确授权该外部写入后，才通过已认证 GitHub 能力启用；
3. 公开 API 复核 enabled=true；
4. 更新 SECURITY.md 的支持范围、精确入口和保密报告说明；
5. 若任一步不成立，停止本切片，不把未启用功能写成可用。

### 6.2 测试治理与 CI 消费者切片

- SoftwareTesting/PROTOCOL.md：删除 T-PROJECT 的旧集成运行资产阶段；
- SoftwareTesting/SAFETY.md：删除 T-PROJECT 对 BBDown、FFmpeg 子进程的旧声明；
- SoftwareTesting/docker/README.md：补全 .dockerignore、CI workflow 与 PR affected-only 输入；
- .github/workflows/ci.yml：删除浏览器安装与安装目录绑定、全部 pip cache 配置和历史分支条件；
- .github/workflows/docker-image.yml：增加 pull_request 与精确路径，删除 GHA Buildx 缓存；
- .github/workflows/launcher.yml：删除 pip cache 配置；
- tests/_v070_frontend_architecture_original.py：把安装产物绑定改为复用既有浏览器断言；
- tests/test_v060_release.py：删除历史分支正向断言并增加历史选择器负向断言；
- tests/test_v070_release.py：覆盖 Docker 输入／PR 触发、无持久 Actions cache 和浏览器无安装边界。

### 6.3 当前文档事实与删减切片

- CHANGELOG.md：把未发布区收敛为当前净状态；
- docs/设计文档.md：让易漂移数值回到字段契约唯一所有权；
- docs/运维/备份恢复与V0.4迁移.md：区分 Docker/NAS 与 Windows EXE 迁移；
- docs/运维/Docker镜像打包与离线交付.md：退出日期验证结果，只留稳定重验规则。

### 6.4 精确实施文件

除生命周期文件外，确定实施文件共 14 个：

1. SECURITY.md
2. CHANGELOG.md
3. docs/设计文档.md
4. docs/运维/备份恢复与V0.4迁移.md
5. docs/运维/Docker镜像打包与离线交付.md
6. SoftwareTesting/PROTOCOL.md
7. SoftwareTesting/SAFETY.md
8. SoftwareTesting/docker/README.md
9. .github/workflows/ci.yml
10. .github/workflows/docker-image.yml
11. .github/workflows/launcher.yml
12. tests/_v070_frontend_architecture_original.py
13. tests/test_v060_release.py
14. tests/test_v070_release.py

实施授权不自动扩展到列表外文件。唯一例外是第 8 节列明的生命周期保存、状态和归档文件。

## 7. 实施与验证顺序

### 7.1 实施前只读预检

1. 重新读取适用 AGENTS.md；
2. 检查工作树、确定文件 diff、活动方案唯一性和待办状态；
3. 重新读取十项发现的权威片段和直接消费者；
4. 公开复核 GitHub 私密漏洞报告状态与当前仓库身份；
5. 任一确定文件出现无法区分的用户修改、权威变化或候选实质漂移时停止，只申请差额。

### 7.2 本地确定变更

1. 先修改测试治理权威中的退出职责和 T-DOCKER 输入；
2. 再修改三个 workflow；
3. 同步三个直接回归文件；
4. 更新迁移、CHANGELOG、Docker 手册与设计文档；
5. 不在外部设置未启用时提前修改 SECURITY.md 的可用入口承诺。

### 7.3 外部设置停点

若用户后续授权实施但没有同时明确授权“启用 GitHub Private Vulnerability Reporting”，普通任务可以完成其他本地确定切片，但必须在本切片停下，保持待办和方案活动，不关闭任务。

若用户同时明确授权外部设置，则在已认证会话中只改变该精确仓库的单一设置；不修改其他安全功能、Issue、advisory、分支保护或仓库设置。

### 7.4 普通验证

所有本地动态验证使用项目现有 Python 3.11 和仓库外隔离 run-id；不安装依赖、不启动产品、不使用真实数据。

阶段 V1：静态候选检查

- git diff --check；
- 精确搜索安装浏览器、历史分支、cache: pip、cache-to: type=gha 等退出标识；
- 核对三个 workflow 仍为 contents: read、无 GHCR 登录、无 packages: write、无 push: true；
- 核对 Docker paths 同时覆盖 push main 与 pull_request、.dockerignore 和 ci.yml。

阶段 V2：聚焦 Python 回归

通过现有隔离 helper 创建仓库外 run-id，并在该运行根设置配置、userdata、缓存、临时目录和 pytest basetemp。执行：

    python -B -X utf8 -m pytest -q -p no:cacheprovider --tb=short \
      tests/test_v060_release.py \
      tests/test_v070_release.py \
      tests/test_v070_frontend_architecture.py \
      tests/test_repository_layout.py \
      tests/test_t_project_isolation.py \
      launcher/tests/test_app_integration.py

再对三个改动的 Python 测试文件执行 Ruff no-cache。若现有 Python 或依赖不可用，记录 blocked，不安装、不升级。

阶段 V3：文档门禁

    python -B -X utf8 -m unittest discover \
      -s SoftwareTesting/doc_consistency \
      -p test_doc_consistency_rules.py

    python -B -X utf8 \
      SoftwareTesting/doc_consistency/test_doc_consistency.py \
      --workspace-root .

生命周期关闭后重新运行实际 T-DOC，因为待办、方案路径和归档状态变化会使先前文档证据失效。

阶段 V4：安全设置复核

- 经单独授权启用设置后，公开读取仓库 private-vulnerability-reporting API；
- 只有 enabled=true 才验证 SECURITY.md 精确入口；
- 不创建 advisory、不提交漏洞内容、不上传本地材料。

### 7.5 验证身份、失效与复用

| 阶段 | 绑定输入 | 失效条件 | 最低复用证明 |
| --- | --- | --- | --- |
| V1 | 三个 workflow、三个回归文件及当前差异 | 任一 workflow、断言或授权边界变化 | 逐文件 diff 未变化且退出标识重查 |
| V2 | 当前源码、测试实现、选择文件、Python 3.11 环境 | 相关测试、helper、workflow 或产品契约变化 | 同一工作树身份、相同选择器和运行根所有权 |
| V3 | 全部活动 Markdown、待办、方案、归档入口、T-DOC 资产 | 任一活动文档或生命周期状态变化 | 当前活动集合与 T-DOC 资产未变；关闭后必须重跑 |
| V4 | 精确 GitHub 仓库、设置状态和 SECURITY.md | 仓库、设置或报告入口变化 | 同一仓库公开 API 仍为 enabled=true |

“只改文档”“上一轮通过”或“产品源码未变”都不能单独复用相应阶段。

### 7.6 动态预算与环境边界

- 聚焦 pytest：6 个文件，预计 0 次产品进程、0 次浏览器、0 次 Docker、0 次 GUI、0 次真实网络；保守预计 1–5 分钟；
- Ruff：3 个文件，0 次产品启动，预计少于 1 分钟；
- T-DOC：2 个入口，0 次产品启动，预计少于 2 分钟；
- 安全设置：1 次精确外部设置写入和 1 次公开 GET；需要已有认证，预计少于 2 分钟；
- 不运行 hosted CI、Docker build、Playwright、Windows EXE、自检候选、全量测试或正式认证；
- 测试 run-id 默认保留；本方案不列明删除，不进行强制清理。

实际耗时以运行结果为准；环境阻断不得改写为产品失败。

### 7.7 当前实施与验证结果（2026-08-13）

- 本地实施：第 6.1 至 6.3 节的确定切片均已完成；`SECURITY.md` 已写入当前维护对象、冻结历史产物边界和精确私密报告入口。
- V1：通过。`git diff --check` 无错误；活动 workflow 中未发现浏览器安装、历史分支选择器、pip／GHA 持久缓存、`packages: write`、登录动作或 `push: true`；三个 workflow 均保持 `contents: read`，Docker 多架构验证同时覆盖 main push 与 pull request 的精确输入并保持 `push: false`。
- V2：通过。仓库外 run-id 为 `doc-consistency-20260813`；Python 3.11.1 聚焦回归结果为 41 passed、1 skipped，三个改动测试文件的 Ruff 0.12.5 检查通过。
- V3：通过。T-DOC 规则夹具 29 项通过；目标 T-DOC 首次运行发现本活动方案缺少骨架要求的三个验证决策字段，补齐后复跑通过且为 0 warning。生命周期关闭会改变活动集合，届时仍须按第 8.3 节再次运行。
- V4：通过。用户单独授权后，仅为 `kachekakaka/bili_workspace` 启用 Private Vulnerability Reporting；已认证读取和公开无缓存读取均返回 `enabled=true`，并确认 `SECURITY.md` 指向 `security/advisories/new`。未创建 advisory、未提交漏洞内容、未修改其他仓库设置。
- 不在本方案范围内的 hosted CI、Playwright、Docker 构建、Windows EXE、自检候选、全量测试和正式认证均为 `not_run`。
- 生命周期关闭：已完成。活动待办已退出，方案已移入归档并登记两个归档索引，本任务创建的空 `docs/方案` 目录已精确删除；关闭后的目标 T-DOC 通过且为 0 warning。

## 8. 生命周期保存与关闭

### 8.1 本次保存

本次用户只授权：

- 创建 docs/方案/DOC-CONSISTENCY-20260813-现行文档与验证消费者一致性收口.md；
- 在 docs/已知问题与待做需求.md 登记同 ID 的“待确认”待办和实际链接；
- 对这两个保存结果做只读机械核对。

本次不进入实施中，不修改第 6.4 节文件，不运行第 7 节验证。

### 8.2 实施开始

只有用户后续明确授权“按已确认方案实施”后，待办才转为实施中。该授权覆盖确定的本地文件、普通验证和满足完成条件后的生命周期关闭，但不自动覆盖 F-01 的外部 GitHub 设置；授权语句必须另行明确包含该设置。

### 8.3 关闭

十项发现和所需普通验证全部完成、外部安全设置已启用并复核、没有授权差额时：

1. 据实填写本方案实施与验证结果，不预写未运行项目；
2. 从 docs/已知问题与待做需求.md 删除本待办；
3. 将本方案完整移动到 archive/docs/plans/DOC-CONSISTENCY-20260813-现行文档与验证消费者一致性收口.md；
4. 更新 archive/docs/plans/README.md 和 archive/docs/README.md；
5. 若 docs/方案 只由本任务创建且移动后为空，凭本方案和实施授权精确删除该空目录；
6. 重新运行 T-DOC；
7. 不生成施工后反哺报告。

关闭不以 commit、push 或 PR 为前提，也不授权这些动作。

## 9. 实施期漂移分流

- 原范围消费者漂移：直接消费 F-01 至 F-10 已确定不变量，且现有权威唯一裁决时，可在本方案文件和一层直接依赖内做最小修复，并重跑受影响阶段；
- 临时环境阻断：保留 run-id、状态、恢复条件和当前证据，不修改产品语义；
- 新范围问题：需要新产品语义、新权限、新副作用、确定列表外文件或新的外部设置时停止并申请差额；
- 独立非阻断问题：先去重，收尾前只统一询问一次是否登记到现有待办入口；用户不选择时不写入。

不得把实施期新发现倒填为本轮静态审计已经评审的 F-01 至 F-10。

## 10. 技术终态、正式终态与残余

预期技术终态：

- 活动文档、测试治理、workflow 和静态回归对十项契约一致；
- GitHub 私密漏洞报告真实可用；
- 聚焦回归与 T-DOC 对当前候选给出可判定结果；
- 没有引入产品行为、schema、API、二进制或发布能力变化。

不属于本方案正式终态：

- hosted GitHub Actions 实际运行；
- Playwright 浏览器动态通过；
- Docker 单／多架构实际构建；
- Windows EXE、FFmpeg 或 launcher candidate 构建；
- 全量测试、正式认证、部署、签名、发布、commit、push 或 PR。

上述未运行项目最终保持 not_run，不得据本方案使用“CI 全绿”“Docker 已验证”“Windows 已认证”或“正式发布就绪”等更强结论。

## 11. 两轮方案自审

### 第一轮：完整性与可施工性

- 39 份活动文档均有覆盖状态；
- F-01 至 F-10 均绑定权威、直接证据、影响、确定处置、文件和验证；
- 14 个实施文件与发现矩阵完全对应；
- 安全外部设置、原范围漂移、环境阻断、生命周期和验证失效均有停点；
- 没有未决语义问题；F-01 已记录用户决定。

结果：通过。

### 第二轮：最小化、授权与删减

- 不修改已经正确的需求、字段契约、ADR、产品实现、配置模板或二进制；
- 不创建新 ADR，不重写归档正文，不恢复旧运行链；
- 设计文档和 Docker 手册优先删除重复值与动态结果；
- CI 只删除与当前契约冲突的安装、缓存和历史分支条件，保留当前验证与短期 artifact；
- 保存、实施、GitHub 外部写入、验证和关闭授权彼此分离；
- 不安排全量测试、正式认证或施工后反哺报告。

结果：通过。

## 12. 完成条件与停止条件

完成条件：

1. F-01 至 F-10 全部按冻结处置落实；
2. 14 个确定文件没有范围外语义变化；
3. GitHub 私密漏洞报告为 enabled=true，SECURITY.md 精确入口可用；
4. V1 至 V4 的适用阶段按实际得到可判定结果；
5. 未运行验证明确为 not_run；
6. 待办、方案、归档索引和 T-DOC 最终一致；
7. 不生成施工后反哺报告。

立即停止条件：

- 用户修改与确定文件发生无法安全合并的冲突；
- 权威、GitHub 仓库身份、外部设置或官方 runner 前提发生实质变化；
- 需要安装依赖、启动产品、访问真实数据、运行全量测试或正式认证；
- 需要列表外文件、额外外部写入、费用、认证范围扩大、commit、push、PR 或发布；
- 验证升级或发现新的语义决定。

遇到停止条件时只申请最小授权或决定差额，不扩大既有授权。
