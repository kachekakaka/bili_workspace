# 运行资产、测试治理与界面契约一致性收口方案

- 待办 ID：`DOC-CONSISTENCY-20260809`
- 状态：已完成
- 方案主责：收口审计发现的 F-01～F-08，使活动文档、运行资产、测试入口、CI、界面契约和机械门禁重新形成可验证的一致闭环
- 测试层级：普通受影响验证、已授权的集成运行包重建、T-DOC 与严格 Windows T-PROJECT full；Docker 构建保持显式授权停点
- 验证影响域：Windows 集成运行资产及来源说明、T-PROJECT Windows/CI 消费者和结果证据、Playwright 隔离、前端样式与缓存身份、Docker workflow 路径触发、T-DOC Markdown 枚举边界及其直接结构消费者
- 具体验证项：已按“验证、输出与授权停点”执行规则夹具、受影响 pytest、源码结构检查、静态脚本检查、运行包重建、T-DOC 和严格 Windows T-PROJECT full；Docker 构建未获授权并保持 `not_run`

## 目标、决定与非目标

### 目标

1. 应用版本继续为 `0.7.0`，本轮已经改变内容的 Windows 集成运行资产使用新的 `runtime_bundle_version=0.5.7`，并让构建器、包内身份、顶层清单、校验器、测试和活动文档一致。
2. Windows 自检只有在最终 `results/result.json` 成功记录后才能报告成功；记录失败必须以非零退出码结束。
3. Playwright 继续归属 T-PROJECT，不新增 Registry 项；CI 只保留一个 canonical 浏览器阶段，并遵守仓库外 run-id、环境隔离和结果记录契约。
4. 桌面普通、紧凑和主要操作控件分别落实 40px、32px 和 48px；移动端可触控控件不低于 44px，CSS token 只由 tokens 层拥有。
5. Docker 构建验证的路径触发器覆盖 Dockerfile 实际复制的所有根级输入。
6. T-DOC 只检查活动项目 Markdown 和允许的归档索引，不扫描 `.runtime` 中的依赖许可证文档。
7. 第三方说明准确描述当前 Windows FFmpeg 的构建来源、版本成员和哈希承接位置。

### 已确认的用户决定

- 当前应用版本是 `0.7.0`，不升级应用版本。
- 当前运行包内容已经变化，因此 Windows 集成运行资产目标版本升级为 `0.5.7`；它仍与应用版本独立。
- 用户选择 full 一致性检查并要求静态评审 2 轮；实际已经完成 2 轮。
- 用户已授权按本方案实施、运行普通受影响验证，以及固定来源的大体积运行包下载、仓库外构建与精确覆盖；T-DOC/T-PROJECT full、真实浏览器、Docker 构建和 Git/远端动作仍未授权。

### 非目标

- 不恢复 tag、GitHub Release、GHCR 正式镜像或其他正式发布能力。
- 不改变应用 `0.7.0`、数据库 schema v4、API、权限、下载算法、持久化目录或产品支持边界。
- 不重写归档正文，不修改历史 `0.5.6` 应用版本示例、历史发布文件名或只承担历史职责的测试数据。
- 不访问真实配置、Cookie、数据库、媒体、用户浏览器 profile 或其他真实数据。
- 不安装浏览器，不派发 workflow，不执行 commit、push、PR 或发布。
- 不自动清理仓库外 run-id、构建缓存、浏览器安装或其他所有权不明的产物。

## 审计基线与冻结范围

### 当前基线

- 审计基线为 `main@157105da3ac9f75a78f6d60140f3401f91889441`，分支与 `origin/main` 无已知提交分歧。
- 保存前工作区有 32 个已修改文件和 3 个未跟踪文件；这些未提交内容全部属于审计候选基线，不得在实施时用 HEAD 内容覆盖。
- 本次方案保存只新增本方案并在 `docs/已知问题与待做需求.md` 登记一条待办，不接管、格式化或回退其他既有修改。
- 普通实施开始前必须重新读取 Git 状态和每个目标文件相对保存基线的差异。目标文件出现保存后新增的未知修改、候选身份变化或与本方案冲突时立即停止。

### 文档与证据边界

- full 检查完整读取 29 份活动 Markdown，并把 `archive/docs/README.md` 和 `archive/docs/plans/README.md` 作为导航与生命周期上下文。
- 归档正文、项目级 Agent Skill 工具资产、真实运行数据和未被活动声明锚定的实现不进入事实结论。
- 实现证据只读取活动文档直接点名的源码、配置、测试、workflow 及一跳直接消费者。
- 检查和两轮评审均为静态只读；没有运行 T-DOC、T-PROJECT、pytest、Node、Playwright、Docker、运行包构建或远端 CI，当前结果全部为 `not_run`。

## 覆盖与残余矩阵

| 维度 | 精确范围 | 状态 | 发现或残余 |
| --- | --- | --- | --- |
| 所有者与导航 | AGENTS、README、docs、SoftwareTesting、归档索引 | 已覆盖 | 入口和生命周期静态一致 |
| 产品与字段事实 | 应用版本、schema、配置、API、持久化边界 | 已覆盖 | 应用 `0.7.0` 和 schema v4 一致；运行资产身份见 F-01 |
| 测试治理 | Registry、协议、安全、T-DOC、T-PROJECT | 已覆盖 | 结果闭环、CI 隔离和扫描边界见 F-02、F-03、F-08 |
| 前端行为与职责 | 控件高度、CSS 四层、浏览器缓存身份 | 已覆盖 | 见 F-04、F-05 |
| 构建与第三方来源 | Windows packs、manifest、Docker、第三方说明 | 已覆盖 | 见 F-01、F-06、F-07 |
| 外部公开事实 | QNAP CPU 架构和 Container Station 导入格式 | 已覆盖 | 官方资料支持当前声明 |
| 动态行为与正式证据 | 本地/CI 测试、浏览器、Docker、运行包冒烟 | 未运行 | 保持 `not_run`，按后续授权停点执行 |

本矩阵不声明正式认证、真实部署、远端 CI 或全项目测试充分性已经通过。

## 差异、影响与确定处置

### F-01：运行资产内容变化但身份仍为 0.5.6

- 证据：两个 `vendor/windows/*-runtime.pack`、`vendor/windows/runtime-manifest.json` 中的哈希和大小已经变化，`tools/build_integrated_runtime.py`、`tools/verify_source.py`、`tests/test_integrated_runtime.py` 和活动文档仍固定 `0.5.6`。
- 影响：同一版本标签对应不同资产内容，削弱包缓存、恢复、审计和问题定位语义；bootstrap 虽同时校验 manifest SHA 与 pack 哈希，但不能替代已确认的版本治理规则。
- 确定处置：应用保持 `0.7.0`；构建器 canonical 常量改为 `0.5.7`，校验器复用该真源而不另存独立字面量；从固定来源重新生成两个 pack 和顶层 manifest，使包内 `BILI_RUNTIME.txt`、manifest、哈希、大小和测试一致。
- 文档职责：`docs/字段契约.md` 承接当前字段值；`vendor/windows/README.md` 和 `THIRD_PARTY_NOTICES.md` 尽量引用 manifest/字段真源，避免重复维护当前数字；`CHANGELOG.md` 记录未发布变更。
- 最小补证：静态读取两个 pack 内部元数据和逐文件清单，证明均为 `0.5.7`；顶层 manifest 哈希和大小与文件完全一致。

### F-02：verify.bat 吞掉最终结果记录失败

- 证据：`verify.bat` 的 `:record_result` 在 PowerShell 失败后只打印警告，随后无条件 `exit /b 0`；成功路径也不检查该子程序返回值。
- 影响：命令可能以零退出并显示通过，但缺少测试契约要求的最终结果文件，形成不可判定的假成功。
- 确定处置：`:record_result` 原样传播记录器退出码；所有可能返回成功的调用点必须检查记录结果，写入失败时打印精确日志路径并非零退出。原本已经失败的路径继续保留原失败语义，不能因第二次记录失败变成成功。
- 最小补证：结构测试证明子程序不再无条件返回 0、成功路径检查返回码；严格 Windows full 的最终 run-id 必须同时具有零退出码和 `status=passed`。

### F-03：两个 CI 浏览器消费者重复且绕过 run-id 隔离

- 证据：`.github/workflows/ci.yml` 与 `.github/workflows/ui-v062.yml` 在相同触发面直接运行 `pytest -m playwright`，没有创建 T-PROJECT run-id、隔离 HOME/cache/tmp/profile 或记录 `results/result.json`；后者的唯一额外价值是日志 Artifact。
- 影响：活动自动化与 `SoftwareTesting/SAFETY.md` 不一致，同一阶段重复消耗资源并产生两套结果入口。
- 确定处置：新增内部 CI 消费脚本 `scripts/dev/run-playwright-phase.sh`，使用 `tools/t_project_isolation.py` 创建仓库外 run-id，设置全部隔离环境，调用 `tools/playwright_runtime.py --probe`，运行 marker、记录最终状态并输出证据目录。
- CI 收口：`.github/workflows/ci.yml` 保留唯一浏览器作业，先安装 CI 前置并解析既有浏览器路径，再调用内部脚本；以 `if: always()` 上传整个 run-id 证据。将 JS 语法检查和短期日志价值保留在 canonical CI 后，精确删除 `.github/workflows/ui-v062.yml`。
- 治理：Registry 仍只有 T-DOC 与 T-PROJECT；新脚本不是新的测试项或权威入口。同步 `SoftwareTesting/project/README.md` 和 `scripts/README.md` 的消费者说明。
- 最小补证：结构测试证明活动 workflows 中只剩一个 `-m playwright` 消费者，且该消费者包含 run 创建、隔离环境、浏览器探测、`--basetemp`、结果记录和证据上传。

### F-04：主要操作按钮 48px 契约未落实

- 证据：`web/assets/styles/tokens.css` 定义 `--control-height-lg: 48px`，但项目中没有样式使用该 token；现有测试只断言 token 存在。
- 影响：桌面主要操作按钮仍受 40px 普通按钮规则约束，与需求文档不一致；机械测试形成虚假的契约覆盖。
- 确定处置：为非紧凑 `.btn.primary` 使用 48px token，同时处理 `.toolbar .btn` 的固定高度，确保 toolbar 不把主要操作重新压回 40px；`.btn.primary.small` 继续使用紧凑规则。
- 缓存身份：CSS 改动后把前端缓存身份统一升级为 `20260809-1`，同步 `web/index.html`、`web/assets/app/main.mjs` 和直接版本断言；这不改变应用版本 `0.7.0`。
- 最小补证：静态断言 token 有实际消费者；Playwright 在桌面证明紧凑/普通/主要操作为 32/40/48px，在移动断点证明可触控控件均不低于 44px。

### F-05：pages 层重复拥有 token 并保留版本覆盖表述

- 证据：`web/assets/styles/pages.css` 以“v0.6.2 UI normalization overrides”开头，并再次定义三个 control-height token。
- 影响：与设计文档的 tokens/base/components/pages 四层职责冲突，未来改动可能再次只更新其中一份。
- 确定处置：删除 pages 层的 `:root` 重定义和版本覆盖说明；保留当前页面选择器，不进行无必要的 `v062-*` 类名批量重命名。
- 最小补证：结构测试证明三个 token 只由 `tokens.css` 定义，`pages.css` 只能消费。

### F-06：Windows FFmpeg 来源说明已失真

- 证据：`THIRD_PARTY_NOTICES.md` 声明 `ffmpeg-n8.1-latest-win64-gpl-8.1`，当前构建器实际从 `imageio_ffmpeg-0.6.0` Windows wheel 提取 `ffmpeg-win-x86_64-v7.1.exe`。
- 影响：第三方来源、二进制版本和复核路径无法从活动说明准确重建。
- 确定处置：按当前固定构建器描述 wheel、成员路径、上游 URL/SHA 承接位置、包内 `checksums.sha256` 和顶层 pack hash；不虚构未验证的发布目录或直接二进制清单。
- 最小补证：静态测试把第三方说明中的来源 token 与构建器常量、manifest source 字段和包内元数据绑定。

### F-07：Docker workflow 路径触发器漏掉实际构建输入

- 证据：`docker/Dockerfile` 复制根 `.env.default`、`THIRD_PARTY_NOTICES.md` 和 `LICENSES/`，`.github/workflows/docker-image.yml` 的 `paths` 没有覆盖这些输入。
- 影响：这些文件改变时不会自动触发镜像构建验证，CI 可能保留过期证据。
- 确定处置：补入三个精确路径；保留现有 main push、`contents: read`、`push: false` 和无发布能力边界。
- 最小补证：结构测试逐项证明 Dockerfile 的根级 COPY 输入被 workflow paths 覆盖，且发布禁令断言继续成立。

### F-08：T-DOC 把 .runtime 依赖文档当作活动文档

- 证据：`SoftwareTesting/doc_consistency/test_doc_consistency.py` 递归枚举 Markdown，但 `IGNORED_PARTS` 没有 `.runtime`；当前工作区实际存在 5 份 `.runtime/python/Lib/site-packages/**/LICENSE.md`。
- 影响：依赖升级可无关地改变 T-DOC 输入、产生错误链接/导航告警，并使“活动 Markdown”范围失真。
- 确定处置：把精确路径片段 `.runtime` 加入统一排除逻辑，不按 `LICENSE.md` 文件名宽泛忽略其他项目文档；同步 T-DOC README 的输入说明。
- 最小补证：规则夹具证明 `.runtime` 下 Markdown 被排除，而普通项目目录中的同名许可证 Markdown 仍参与检查。

## 确定实施范围

### F-01 与 F-06：运行资产和来源

- `tools/build_integrated_runtime.py`：目标 runtime bundle 为 `0.5.7`，保持当前固定 Python、BBDown 和 FFmpeg wheel 来源。
- `tools/verify_source.py`：复用 canonical 版本真源，校验新 manifest、包哈希和大小。
- `vendor/windows/python-runtime.pack`、`vendor/windows/media-runtime.pack`、`vendor/windows/runtime-manifest.json`：在明确授权后精确重建和覆盖。
- `tests/test_integrated_runtime.py`：更新版本、哈希、大小、内部元数据和来源绑定断言。
- `docs/字段契约.md`、`vendor/windows/README.md`、`THIRD_PARTY_NOTICES.md`、`CHANGELOG.md`：同步当前事实并删减重复所有权。

### F-02 与 F-03：T-PROJECT 结果和 CI 浏览器阶段

- `verify.bat`：传播最终记录失败。
- 新增 `scripts/dev/run-playwright-phase.sh`：承接 CI 浏览器阶段的 run-id、隔离、探测、marker、结果和日志。
- `.github/workflows/ci.yml`：调用唯一内部消费者并上传 run 证据。
- 精确删除 `.github/workflows/ui-v062.yml`；其日志价值先迁入 canonical CI。
- `SoftwareTesting/project/README.md`、`scripts/README.md`：同步唯一消费者和隔离边界。
- `tools/verify_source.py`：把新脚本加入必要源码边界。
- `tests/test_t_project_isolation.py`、`tests/test_integrated_runtime.py`、`tests/test_v070_frontend_architecture.py` 及其原始模块：增加结果传播、唯一消费者和 CI 隔离断言。

### F-04 与 F-05：样式和前端缓存身份

- `web/assets/styles/pages.css`：删除重复 token/版本覆盖说明，落实主要操作高度和 toolbar 级联。
- `web/assets/styles/tokens.css`：保持 control-height 唯一所有者，除非实现证明需要最小注释调整。
- `web/index.html`、`web/assets/app/main.mjs`：统一使用前端缓存身份 `20260809-1`。
- `tests/test_v062_ui.py`、`tests/test_v062_ui_playwright.py`、`tests/test_browser_version.py`、`tests/test_v060_release.py`、`tests/test_v070_release.py`、`tests/test_v062_settings_ui.py`：同步静态、级联和缓存身份断言。

### F-07：Docker 构建触发

- `.github/workflows/docker-image.yml`：增加 `.env.default`、`THIRD_PARTY_NOTICES.md`、`LICENSES/**`。
- `tests/test_integrated_runtime.py` 与 `tests/test_v070_release.py`：覆盖构建输入并保持无发布能力断言。

### F-08：T-DOC 边界

- `SoftwareTesting/doc_consistency/README.md`：明确排除生成运行时。
- `SoftwareTesting/doc_consistency/test_doc_consistency.py`：精确忽略 `.runtime`。
- `SoftwareTesting/doc_consistency/test_doc_consistency_rules.py`：增加运行时与普通许可证 Markdown 的正反夹具。

### 明确不改

- `AGENTS.md`、应用版本常量、数据库 schema、业务源码、API、真实配置和真实数据。
- `archive/**` 历史正文，包括当前未跟踪的已完成历史方案。
- `tests/test_playwright_layout.py` 和 `tests/test_server_instance.py` 中用于旧应用兼容场景的 `0.5.6` 示例。
- `tests/test_repository_layout.py` 中历史发布说明文件名 `V0.5.6_发布与验证说明.md`。
- tag、Release、GHCR、分支、索引和 Git 历史。

## 实施顺序与停止条件

1. 重新冻结 Git 状态、全部目标文件和一层直接消费者；与保存基线对比，发现未知修改或重叠冲突时停止。
2. 先调整字段所有权、第三方来源说明、T-PROJECT 消费者职责和完成条件，不把计划结果预写成已经通过。
3. 完成 F-08 的 T-DOC 排除和规则夹具。
4. 完成 F-02 的结果传播，再新增隔离浏览器阶段脚本、迁移 CI 日志并删除重复 workflow。
5. 完成 F-04/F-05 的 CSS、缓存身份和直接测试。
6. 完成 F-07 的 Docker 路径触发和结构断言。
7. 到达运行包重建停点：展示固定下载来源、预计写入的两个 pack 和 manifest 绝对路径，取得明显大体积下载、构建及精确覆盖授权后才执行 F-01/F-06 的重建。
8. 完成普通受影响验证。任何仓库内缓存、真实数据访问、用户 profile 复用、未知进程、未列明下载、宽泛删除或新增发布能力都立即停止。
9. 分别申请 T-DOC、严格 T-PROJECT full/真实无头浏览器以及可选 Docker 构建授权；未授权项目保持 `not_run`。
10. 只有所有必需完成条件得到可判定证据后才能关闭待办和归档方案。

出现新语义决定、runtime 目标不再是 `0.5.7`、前端缓存身份冲突、需要改动排除文件或远端状态时，视为候选实质漂移，只申请授权差额。

## 验证、输出与授权停点

保存方案时以下全部为 `not_run`，不得把计划命令写成实际结果。实施阶段的当前实际结果如下：

### 当前实施进展

- F-01～F-08 的确定代码与文档增量已经完成；F-01 构建器、校验器、字段契约、顶层 manifest 和两个 pack 已统一为 `0.5.7`，构建器显式面向 `win_amd64`、CPython 3.13、ABI `cp313` 解析锁定依赖。
- 首轮普通受影响 pytest run-id `20260809T071625Z-e407b4aa438e` 为 `failed`：84 passed、5 failed、3 skipped、2 subtests passed。失败均为新结构断言表达不准确，修复时没有放宽实际契约。
- 最终普通受影响验证 run-id `20260809T071714Z-c64879bcedba` 中 pytest 为 89 passed、3 skipped、2 subtests passed；源码结构检查、受影响 Ruff、两个 Shell 脚本静态语法和前端主模块 Node 语法均通过。
- 普通受影响验证 run-id 的 `results/result.json` 明确保持 T-DOC、T-PROJECT full、真实浏览器、运行包重建和 Docker 构建为 `not_run`；该记录准确反映其当时范围。
- 运行资产 run-id `20260809T072331Z-87eba371ba13` 为 `passed`：固定来源 SHA 校验、可移植 Python/BBDown/FFmpeg 冒烟、候选包 1,576/8 条内部逐文件哈希、顶层 manifest、覆盖后的源码结构检查、12 项目标 pytest、Ruff 和 `git diff --check` 均通过。Python pack 为 66,009,509 字节、SHA-256 `14d86f9af404a4e249e42f1cf0848052ce09875295a44becb1a9365a7f0652ce`；media pack 为 39,154,660 字节、SHA-256 `0b8bb0e7125922faa684e2edb015b5e0d8e81c2d3151ff78dbe46083fe66c24d`；顶层 manifest SHA-256 为 `168c2b5d510f65badeb03573797d4504add26629e9be4eac10e02043c35bda8c`。
- T-DOC full run-id `20260809T073129Z-a4fef30bbe96` 为 `passed`，目标项目文档机械门禁为 0 warning。
- 首轮严格 Windows T-PROJECT run-id `20260809T073158Z-06107e5c4a65` 准确记录为 `failed`：pytest 为 311 passed、6 skipped、2 warnings、2 failed，分别暴露 `verify.bat` 新增块混入裸 LF，以及移动端高度测试错误复用桌面隐藏表格中的 locator。修复只统一批处理文件为 CRLF，并改取可见的移动卡片按钮，没有放宽高度契约。
- 修复预检 run-id `20260809T073720Z-9530e0c95edd` 为 `passed`：6 项受影响测试和 Playwright 测试文件 Ruff 通过。
- 最终严格 Windows T-PROJECT full run-id `20260809T073731Z-5478dda4a5b7` 为 `passed`、退出码 0，实际复用 `C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe`。全量 pytest 为 313 passed、6 skipped、2 warnings；源码结构、集成运行资产、compileall、Ruff、Node 语法、Node 单元测试和真实 Playwright 阶段均已执行并通过，`results/result.json` 已成功记录。
- 生命周期关闭后的首轮 T-DOC run-id `20260809T074237Z-5332ddaa7c4c` 为 `failed`，准确发现任务创建的空 `docs/方案` 条件目录仍存在；确认目录为空且所有权明确后精确删除。复验 run-id `20260809T074322Z-771731f18bed` 为 `passed`，T-DOC 0 warning 且 `git diff --check` 通过。

### 普通受影响验证

1. 在仓库外所有权明确的 run-id 中运行以下直接测试，设置 `PYTHONPYCACHEPREFIX`、`--basetemp` 和 `-p no:cacheprovider`：

   - `SoftwareTesting/doc_consistency/test_doc_consistency_rules.py`
   - `tests/test_t_project_isolation.py`
   - `tests/test_integrated_runtime.py`
   - `tests/test_v062_ui.py`
   - `tests/test_browser_version.py`
   - `tests/test_v060_release.py`
   - `tests/test_v070_release.py`
   - `tests/test_v070_frontend_architecture.py`

2. 以 `-B -X utf8` 运行 `tools/verify_source.py`，并对改动的 Python 文件执行 Ruff `--no-cache`。
3. 对 `scripts/dev/verify-source.sh` 和新浏览器阶段脚本执行 `sh -n`；静态解析 YAML，核对唯一 Playwright 消费者和 Docker paths。
4. 只读打开新 pack 时可用 Python `zipfile` 核对元数据和逐文件清单；不得在未获重建授权前改写 pack。

### 运行资产重建停点（已授权并完成）

- 用户已明确授权明显大体积公开下载、仓库外构建目录、Python/BBDown/FFmpeg 冒烟进程，以及精确覆盖两个 pack 和 manifest；实施未扩展到其他来源、进程或目标文件。
- 只允许 `tools/build_integrated_runtime.py` 当前固定的公开来源和 SHA；来源、版本或副作用变化时重新停下。
- 构建输出必须先在仓库外验证，确认 `0.5.7`、内部清单、顶层哈希和大小后再精确替换目标文件。
- 不下载浏览器，不发布 Artifact，不派发 GitHub workflow。

### T-DOC 与 T-PROJECT 停点（已授权并完成）

- T-DOC 属于 Registry `full` 项；用户已明确授权，目标项目 T-DOC 已取得 0 warning 的 `passed` 证据。
- 严格 Windows T-PROJECT full 必须同时要求 Node 与 Playwright，创建并保留仓库外 run-id，启动本次拥有的 Python、BBDown、FFmpeg、Node 和无头浏览器进程。
- 最终证明必须同时包含命令退出码、`results/result.json`、逐阶段日志和浏览器路径；任一缺失均不得记为 `passed`。
- 找不到已有浏览器、缺少依赖或记录失败时按协议记为 `blocked` 或 `inconclusive`，不得自动下载。
- 严格 Windows T-PROJECT full 已由用户明确授权并取得 `passed` 证据；Linux/macOS full、远端 CI 和正式认证保持 `not_run`。

### Docker 停点

- 本方案对 F-07 的必要证明是 workflow 结构与直接断言；实际单架构或多架构 Docker build、容器启动和 QNAP 部署均需另行明确授权。
- Docker 构建未运行可以作为已披露残余，但不能写成镜像已经验证。

### 输出与清理

- 测试、浏览器和构建证据默认保留在带所有权标记的仓库外 run-id。
- 本方案不授权删除 run-id、测试根、构建缓存、浏览器安装或其他仓库外内容。
- 规则夹具只可清理自身创建且所有权明确的系统临时目录。

## 授权边界

| 动作 | 当前状态 |
| --- | --- |
| 保存本待确认方案和对应待办 | 已由用户明确授权 |
| 修改确定实施范围内文件 | 已由用户明确授权实施 |
| 精确删除 `.github/workflows/ui-v062.yml` | 已由本次实施授权覆盖；迁移唯一价值后执行 |
| 普通受影响验证及仓库外 run-id | 已由本次实施授权覆盖 |
| 大体积运行包下载、构建和精确覆盖 | 已由用户明确授权并完成，证据位于 run-id `20260809T072331Z-87eba371ba13` |
| T-DOC、T-PROJECT full、真实无头浏览器 | 已由用户明确授权并完成；最终证据分别位于 run-id `20260809T073129Z-a4fef30bbe96` 和 `20260809T073731Z-5478dda4a5b7` |
| Docker build、容器或真实 QNAP 部署 | 未授权 |
| 删除测试输出或其他文件 | 未授权 |
| commit、push、PR、发布、workflow 派发 | 未授权且不属于完成条件 |

## 完成条件与生命周期收尾

### 主责完成证明

- 应用仍为 `0.7.0`；构建器、两个 pack 内部身份、顶层 manifest、校验器、字段契约和测试一致使用 `runtime_bundle_version=0.5.7`，且哈希/大小完全匹配。
- FFmpeg 活动说明准确对应当前 wheel、成员、来源 SHA、包内校验和与 pack manifest，不再声明 `n8.1` 目录。
- `verify.bat` 最终结果写入失败时非零退出；严格 full 的成功证据同时具备 `status=passed`。
- 活动 workflows 只有一个 T-PROJECT Playwright 消费者；其 profile、HOME、cache、tmp、basetemp、日志和结果全部位于同一 run-id，重复 UI workflow 已精确删除。
- 桌面紧凑/普通/主要操作控件的实际计算高度为 32/40/48px，移动可触控控件不低于 44px；control-height token 只由 tokens 层定义，前端缓存身份统一为 `20260809-1`。
- Docker workflow paths 覆盖 Dockerfile 的根级 COPY 输入，并继续保持 `contents: read`、`push: false` 和无正式发布能力。
- T-DOC 规则夹具证明 `.runtime` 被精确排除、普通许可证 Markdown 没有被宽泛排除；经授权的目标项目 T-DOC 得到可判定结果。
- 所有必要验证按实际结果记录；未运行项目继续明确为 `not_run`，不冒充跨平台或正式认证。
- 最终差异保留保存前用户修改，只包含本方案确定增量和生命周期文件，不覆盖无关工作。

### 关闭时的状态消费者

- `docs/已知问题与待做需求.md`：删除 `DOC-CONSISTENCY-20260809` 条目。
- 本方案：从 `docs/方案/DOC-CONSISTENCY-20260809-运行资产测试治理与界面契约收口.md` 精确移动到 `archive/docs/plans/DOC-CONSISTENCY-20260809-运行资产测试治理与界面契约收口.md`。
- `archive/docs/README.md`：登记历史方案、完成范围和当前承接真源。
- `archive/docs/plans/README.md`：登记已完成方案。
- T-DOC：关闭后再次核对活动待办、活动方案、归档索引和链接。

上述精确仓库内移动和待办删除只有在完成条件满足且后续实施授权覆盖收尾时执行；保存方案不授权提前关闭。

### 关联方案、共享文件与对方职责状态

不适用。保存时没有其他活动待办或活动方案；`archive/docs/plans/DOC-GOV-20260809-文档生命周期与T-PROJECT浏览器测试收口.md` 已属于历史归档，不是本方案的活动依赖。本方案不接管其正文或既有证据。

### 联合只读复核触发条件

不适用。最终只复核 F-01～F-08、确定实施文件、一层直接消费者和本次改动新产生的一跳链接/调用，不重新执行 full 文档审计。

### 验收停点

- T-DOC、严格 Windows T-PROJECT full 和运行资产重建均已得到明确授权及可判定成功证据，方案完成条件已满足。
- 用户拒绝某项必要高副作用验证时，记录残余并重新确认是否允许调整完成条件；不得自行关闭。
- commit、push、PR、远端 CI、正式认证和 Docker 构建不自动成为关闭前提，除非用户后续明确加入。

### 关闭边界与未运行验证

- Linux/macOS full、远端 CI、真实 Docker/QNAP 和正式认证默认不属于完成证明。
- 最终报告必须逐项列出实际运行、结果、证据位置和仍为 `not_run` 的项目。

## 最终范围与漂移复核

实施和关闭时只复核：

1. `docs/README.md`、`SoftwareTesting/README.md`、Registry、字段契约和 T-PROJECT/T-DOC 权威入口；
2. 本方案“确定实施范围”列出的文件；
3. 已列明的一层结构测试、workflow 和脚本消费者；
4. 修改路径新产生的一跳直接链接、导入、缓存身份或自动化调用。

不得递归重做全部产品源码、全部测试正文、归档历史或远端配置。新增文件、下载来源、运行进程、删除目标、测试项、状态 schema、应用版本或发布能力发生变化时，视为候选实质漂移并停止。

## 评审与残余

- 用户选择的评审轮数：2。
- 实际完成的静态评审轮数：2。
- 最终用户决定：应用保持 `0.7.0`，Windows 集成运行资产目标版本为 `0.5.7`。
- 集合对账：审计报告、覆盖矩阵和本方案均使用稳定问题集合 F-01～F-08；每项都有证据、影响、确定处置、目标文件和最小补证，没有遗漏或重复。
- 最终残余：Windows 范围内的普通验证、运行包重建、T-DOC 与 strict T-PROJECT full 已通过；Docker 构建、真实 QNAP、Linux/macOS full、远端 CI 和正式认证保持 `not_run`，Git/远端动作未授权且不属于关闭条件。
