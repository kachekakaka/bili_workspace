# 文档生命周期与 T-PROJECT 浏览器测试收口方案

- 待办 ID：`DOC-GOV-20260809`
- 状态：已完成
- 方案主责：收口活动文档入口、归档生命周期、T-DOC 机械边界，以及 T-PROJECT 内部 Playwright 必需阶段的入口、隔离和结果语义
- 测试层级：普通验证；T-DOC、规则夹具和受影响的结构测试属于本方案普通验证，严格 T-PROJECT full 另设显式授权停点
- 验证影响域：活动 Markdown 导航与生命周期、项目级 Agent Skill 资产排除、T-PROJECT Windows 与 Linux/macOS 入口、Playwright 运行前置与隔离、相关 CI 选择器和直接结构消费者
- 具体验证项：按“验证、输出与授权停点”执行 T-DOC 规则夹具、目标项目 T-DOC、受影响 pytest、源码结构检查和脚本静态检查；取得全量测试授权后再执行严格 T-PROJECT full

## 目标、决定与非目标

### 目标

1. 活动运维文档只指向测试治理权威入口，不再复制一套可能绕过隔离的完整验证命令。
2. 活动 Markdown 只能通过归档索引进入历史材料，T-DOC 对全部活动 Markdown 实施相同规则。
3. T-DOC 精确排除项目级 Agent Skill 工具资产，不把工具说明误判为活动项目文档。
4. Playwright 不新增 Registry 项，而是成为 `T-PROJECT` 的必需阶段；严格运行只有在浏览器阶段实际执行后才能得到 `passed`。
5. Windows 部署自检允许在非严格模式继续完成可用检查，但任何必需阶段被跳过时只能记录 `inconclusive`，不能冒充 T-PROJECT full 通过。

### 已确认的用户决定

- Playwright 不单独登记。
- Playwright 归属 `T-PROJECT full`，原因是接口、权限或响应结构变化可能破坏浏览器调用链，完整项目自检需要共同覆盖。
- CI 可以为了平台环境和并行效率保留独立浏览器作业，但该作业只是 T-PROJECT 的自动化阶段，不形成新的测试项或第二个权威入口。

### 非目标

- 不评价现有测试覆盖率、断言质量、重复度、执行成本或是否覆盖所有 API 与浏览器组合。
- 不核对需求、设计、字段和运维正文中的产品事实。
- 不启动应用服务、真实用户浏览器或容器，不访问真实数据或真实凭据。
- 不恢复 tag、GitHub Release 或 GHCR 正式发布能力。
- 不修改、暂存或覆盖当前已有的 `AGENTS.md` 工作区改动。
- 除用户后续为解除运行包阻断而明确授权的锁定依赖下载与 Windows 集成运行包重建外，不安装或下载浏览器及其他资产。
- 不执行 commit、push、PR、工作流派发或其他远端状态变更。

## 冻结范围与初始证据

### 路线与活动结构

- 本项目是单一上下文成熟项目，采用“等价既有治理”路线，不迁移到另一套标准路径或 schema。
- 协作入口为 `AGENTS.md`；用户入口为 `README.md`；活动文档入口为 `docs/README.md`；测试治理入口为 `SoftwareTesting/README.md`。
- 本次完整读取 29 份活动 Markdown，并读取 `archive/docs/README.md`、`archive/docs/plans/README.md`、`archive/docs/workflows/README.md` 三个直接生命周期索引。
- 当前 `docs/已知问题与待做需求.md` 在保存本方案前没有待办，`docs/方案/` 不存在；归档 Markdown 均由现有归档索引承接。
- 项目没有根 `CONTEXT.md`、`CONTEXT-MAP.md` 或嵌套 `CONTEXT.md`，只有一份适用的根 `AGENTS.md`。

### 直接实现与消费者证据

- T-DOC 的权威入口和实现位于 `SoftwareTesting/doc_consistency/`，CI 通过 `.github/workflows/ci.yml` 直接调用目标项目检查。
- T-PROJECT 的权威入口为 `SoftwareTesting/project/README.md`，Windows 调用 `verify.bat`，Linux/macOS 调用 `scripts/dev/verify-source.sh`。
- `pyproject.toml` 把 `tests/` 设为 pytest 根，并声明 `playwright` marker；七个 Playwright 模块只有在 `BILI_RUN_PLAYWRIGHT=1` 时运行。
- `.github/workflows/ci.yml` 和 `.github/workflows/ui-v062.yml` 已安装 Chromium 并设置 `BILI_RUN_PLAYWRIGHT=1`，说明浏览器阶段存在，但 Registry 仍只登记 T-DOC 与 T-PROJECT。
- `requirements/dev.lock` 已固定 Playwright Python 包；Windows 集成运行包只封装 Python 包，不封装浏览器二进制。
- `tests/test_t_project_isolation.py`、`tests/test_integrated_runtime.py`、`tests/test_v070_release.py` 和 `tests/_v070_frontend_architecture_original.py` 是入口、隔离与工作流选择器的一层结构消费者。

### 排除项

- `app/`、`web/` 和产品测试正文不进入本次结构检查，只有入口直接点名的路径和一层结构消费者进入范围。
- 归档正文不重新审计；只核对索引职责以及活动区对归档的进入方式。
- `.runtime/`、`.cache/`、`.tmp/`、`downloads/`、实际 `userdata/` 和真实配置均排除。
- `.agents/skills/**`、`.cursor/skills/**`、`.claude/skills/**`、`.codex/skills/**`、`.opencode/skills/**`、`.opencode/skill/**` 和 `.github/skills/**` 属于项目级 Agent Skill 工具资产；当前仓库没有这些路径，本方案只补齐未来机械排除能力。
- 内容一致性、测试充分性、安全认证、真实部署、全量 CI 和远端状态均未覆盖。

### 当前工作区

- 保存前只发现 `AGENTS.md` 有未提交修改，内容是提交信息格式规则调整。
- 本方案不修改 `AGENTS.md`。普通任务施工前必须重新读取 Git 状态和全部目标文件差异；任一目标文件出现未知修改时停止，不得覆盖。

## 覆盖与残余矩阵

| 结构维度 | 精确范围 | 状态 | 证据或残余 |
| --- | --- | --- | --- |
| 上下文与路线 | 根规则、公开入口、上下文文件 | 已覆盖（满足） | 单一上下文，成熟项目已有完整入口与生命周期 |
| 结构与职责 | 核心真源、运维、测试治理 | 已覆盖（存在缺口） | 运维手册复制完整验证命令；T-PROJECT 浏览器阶段职责未物化 |
| 入口与导航 | AGENTS、README、docs、SoftwareTesting、归档入口 | 已覆盖（存在缺口） | 一份活动运维手册直接链接归档方案正文 |
| 活动与历史生命周期 | 待办、方案、ADR、运维、归档索引 | 已覆盖（存在缺口） | “历史只由索引承接”未覆盖全部活动 Markdown |
| 待办、方案与记录 | 活动待办、活动方案、归档计划索引 | 已覆盖（满足） | 保存前没有活动待办或方案；保存后由本待办唯一链接本方案 |
| 测试治理结构 | Registry、协议、安全、T-DOC、T-PROJECT、tests 根 | 已覆盖（存在缺口） | Playwright 默认跳过，入口、浏览器前置和结果语义不一致 |
| 机械门禁与授权边界 | T-DOC、源码门禁、CI、测试隔离 | 已覆盖（存在缺口） | T-DOC 未精确排除 Skill 资产，也未阻止全部活动文档直链归档正文 |

内容事实、测试经济性和全项目安全认证不属于本矩阵的满足声明。

## 差异、影响与处置

### 活动运维手册重复完整验证命令

- 证据：`docs/运维/发布与回滚流程.md` 在“源码验证”中复制 T-DOC、源码检查、compileall、Ruff、pytest、Node 语法和 Node tests 命令。
- 影响：直接执行该列表会绕过 T-PROJECT 仓库外 run-id、结果文件和分类语义；`compileall` 等命令还可能在工作树落盘。
- 有效路径：保留重复列表并逐项重建隔离，或删除重复列表并把权威调用方式收口到测试治理入口。
- 确定处置：依据 `docs/README.md` 和 `SoftwareTesting/README.md` 的唯一职责，采用后者；运维文档只解释更新场景并链接 T-DOC、T-PROJECT 权威入口，不再维护第二套完整命令。
- 最小补证：检查运维入口仍能到达两项测试文档，且直接消费者没有继续断言旧命令块。

### 活动文档直链归档正文且门禁覆盖不足

- 证据：`docs/运维/Docker镜像打包与离线交付.md` 直接链接 `archive/docs/plans/DOCKER-QNAP-20260806-QNAP镜像构建验证与私有交付方案.md`；`docs/README.md` 要求历史材料只由归档索引承接。
- 影响：活动手册形成绕过归档索引的历史入口，T-DOC 只检查四个核心导航文件，无法发现普通活动文档中的同类回归。
- 有效路径：允许任意活动专题深链历史正文，或统一经归档索引进入。
- 确定处置：现有生命周期规则唯一裁决为经索引进入；把手册链接改到 `archive/docs/README.md`，保留历史记录名称和“旧结果不可复用”的说明。
- 门禁动作：让归档正文直链检查覆盖全部活动 Markdown，只允许项目定义的归档索引入口；归档区内部链接不受此限制。
- 最小补证：以普通活动专题作为负例、归档索引作为正例补充规则夹具。

### T-DOC 未排除项目级 Agent Skill 工具资产

- 证据：`test_doc_consistency.py` 的 Markdown 枚举和 `_ignored` 只处理缓存、构建和依赖目录，没有识别标准项目级 Skill 根。
- 影响：未来加入项目 Skill 后，其 `SKILL.md`、内部链接、示例路径或 `CONTEXT.md` 可能被错误纳入活动文档、绝对路径警告或上下文形状判断。
- 确定处置：按精确路径片段排除已列七类 Skill 根，应用到 Markdown、上下文和相关遍历；不按文件名宽泛排除其他位置的 `SKILL.md`，也不排除 `archive/docs/skills/` 历史记录。
- 最小补证：规则夹具同时证明标准 Skill 根被排除、普通位置的 `SKILL.md` 仍参与检查。

### Playwright 归属和 T-PROJECT 结果语义不一致

- 证据：Playwright 模块在 `tests/` 中且默认跳过；T-PROJECT 运行无选择器 pytest 后只按退出码记录结果；测试安全当前又禁止 T-PROJECT 启动浏览器。
- 影响：接口或响应结构变化可能破坏浏览器调用链，而严格 T-PROJECT 仍可能在浏览器阶段未执行时记录 `passed`。
- 用户决定：不新增 T-PLAYWRIGHT 或其他 Registry 项；Playwright 是 T-PROJECT full 内部的必需阶段。
- 确定处置：Registry 保留两个测试项，只扩充 T-PROJECT 唯一职责、受管根和阶段映射；CI 的独立作业只是该阶段的自动化执行方式。
- Windows 语义：权威 full 命令同时设置 `BILI_VERIFY_REQUIRE_NODE=1` 与 `BILI_VERIFY_REQUIRE_PLAYWRIGHT=1`。普通 `verify.bat` 可以在非严格部署自检模式下继续，但 Node 或 Playwright 任一阶段跳过时，退出码可以保持零，`results/result.json` 必须为 `inconclusive`。
- Linux/macOS 语义：`scripts/dev/verify-source.sh` 始终执行完整阶段；缺少 Python、Node、Playwright 包或可用浏览器时为 `blocked`。
- 浏览器来源：新增 `tools/playwright_runtime.py`，优先采用显式 `BILI_PLAYWRIGHT_CHROMIUM`，其次只探测已经存在的 Playwright Chromium、Chrome、Edge 或 Chromium；自动发现时逐一执行有界无头探测并在候选不兼容时回退，显式路径失败时不回退。探测使用仓库外 run-id 中的临时目录，不得下载安装浏览器，也不得使用现有用户浏览器配置或登录会话。
- 隔离：浏览器由本次 pytest 直接拥有，只访问测试拥有的回环地址；profile、临时文件、缓存和日志进入 run-id。只能关闭本次启动且有句柄所有权的进程，禁止按名称结束浏览器。
- 结果：找不到或无法启动兼容浏览器时，严格入口为 `blocked`；测试已开始后的断言或浏览器行为失败为 `failed`；运行器异常为 `inconclusive`。
- 最小补证：静态证明 full 入口设置必需开关和 `BILI_RUN_PLAYWRIGHT=1`；单元测试覆盖显式路径、已存在候选、缺失和不安全用户配置边界；经另行授权完成一次严格 Windows T-PROJECT full。

### 直接结构消费者仍断言旧运维标题

- 证据：`tests/test_v060_release.py` 断言“Docker / QNAP 源码更新”，当前手册标题是“Docker 源码构建与更新”，并明确真实 QNAP 部署暂缓。
- 影响：T-PROJECT 会在进入该断言后失败，且旧名称会把已暂缓的部署职责重新混入当前入口。
- 确定处置：只把该结构断言同步到当前标题和职责，不改动其余产品行为断言；不借此重新判断 QNAP 产品事实。
- 最小补证：运行该测试文件并确认没有为了满足旧 token 反向扩大当前运维职责。

### 已有 AGENTS.md 修改

- 处置：排除并保留，不纳入任何实施动作、格式化或关闭清理。
- 停止条件：普通任务发现本方案其他目标文件已有未知改动，或 `AGENTS.md` 修改与目标规则产生真实冲突时停止并报告。

## 目标测试资产信息架构

| Registry ID | 类别 | 权威入口 | 受管实现与选择映射 |
| --- | --- | --- | --- |
| T-DOC | full | `SoftwareTesting/doc_consistency/README.md` | `SoftwareTesting/doc_consistency/test_doc_consistency.py`、规则夹具、活动 Markdown、归档索引和骨架入口；独立于 T-PROJECT 执行 |
| T-PROJECT | full | `SoftwareTesting/project/README.md` | Windows `verify.bat`、Linux/macOS `scripts/dev/verify-source.sh`；pytest 根 `tests/`，Node 根 `tests/frontend/`，Playwright marker 是同一测试项的必需浏览器阶段，源码与运行资产检查由现有 runner 继续承接 |

`SoftwareTesting/README.md` 继续作为测试总入口，`docs/软件测试.md` 继续作为唯一活动 Registry；不得增加第三个浏览器测试项。`.github/workflows/ci.yml`、`.github/workflows/ui-v062.yml` 和 `.github/workflows/build-integrated-runtime.yml` 是直接自动化消费者，不成为新的治理真源。

## 确定实施范围

### 文档入口与字段

- `README.md`：区分普通 Windows 部署自检与严格 T-PROJECT full，并继续把测试选择导向治理入口。
- `CHANGELOG.md`：在“未发布”中记录文档生命周期、Skill 资产排除和 T-PROJECT 浏览器阶段收口，不写成发布结果。
- `docs/软件测试.md`：保留 T-DOC、T-PROJECT 两行，只扩充 T-PROJECT 唯一职责。
- `docs/字段契约.md`：在测试专用字段中承接 `BILI_VERIFY_REQUIRE_NODE`、`BILI_VERIFY_REQUIRE_PLAYWRIGHT`、`BILI_RUN_PLAYWRIGHT` 和 `BILI_PLAYWRIGHT_CHROMIUM` 的所有者、默认语义与使用边界。
- `docs/运维/发布与回滚流程.md`：删除重复完整命令块，链接权威测试入口并同步 Windows 严格调用说明。
- `docs/运维/Docker镜像打包与离线交付.md`：把历史证据链接改到归档索引。

### 测试治理

- `SoftwareTesting/PROTOCOL.md`：声明 T-PROJECT full 包含必需 Playwright 阶段，以及跳过阶段的 `inconclusive` 语义。
- `SoftwareTesting/SAFETY.md`：允许并约束本次直接拥有的无头浏览器、回环网络、临时 profile 和进程清理；继续禁止真实浏览器会话、真实网络和自动下载。
- `SoftwareTesting/project/README.md`：列明受管根、阶段、Windows 严格开关、浏览器前置、结果分类和 CI 消费者。
- `scripts/README.md`：同步普通部署自检与 full 的差异、浏览器前置和无自动下载边界。

### T-DOC 门禁

- `SoftwareTesting/doc_consistency/README.md`：说明全部活动 Markdown 的归档入口规则和项目级 Skill 工具资产排除。
- `SoftwareTesting/doc_consistency/test_doc_consistency.py`：实现精确 Skill 根排除，并把活动文档直链归档正文检查扩展到全部活动 Markdown。
- `SoftwareTesting/doc_consistency/test_doc_consistency_rules.py`：增加普通活动专题、允许的归档索引、标准 Skill 根和普通 `SKILL.md` 的正反夹具。

### T-PROJECT 运行器与实现

- `verify.bat`：增加 Playwright 严格开关、已有浏览器探测、`BILI_RUN_PLAYWRIGHT=1` 接线和 partial/inconclusive 结果组合；保持所有输出在 run-id。
- `scripts/dev/verify-source.sh`：以 `-B -X utf8` 调用浏览器探测，缺少前置时记录 `blocked`，成功后强制运行 Playwright。
- `tools/playwright_runtime.py`：新增共享的只读候选解析和受控无头启动探测；只输出选定的既有浏览器路径，不执行下载、安装或用户 profile 复用。
- `tools/verify_source.py`：把新增工具和测试加入必要源码文件，维持根布局、文本和秘密边界检查。
- `pyproject.toml`：保留 `tests/` 根和 `playwright` marker，补充其为 T-PROJECT 必需阶段的结构说明，不改变 `integration` 的现有保留语义。

### 直接消费者与结构测试

- 新增 `tests/test_playwright_runtime.py`，使用临时假路径验证候选优先级、缺失、拒绝目录/不安全路径和状态分类，不启动真实浏览器。
- 修改 `tests/test_v062_ui_playwright.py`，与其他 Playwright 模块一致地接受解析后的 `BILI_PLAYWRIGHT_CHROMIUM`。
- 修改 `tests/test_t_project_isolation.py`、`tests/test_integrated_runtime.py` 和 `tests/test_v070_release.py`，断言严格开关、run-id 隔离、UTF-8 探测调用和无自动下载。
- 修改 `tests/test_v060_release.py`，只同步当前运维结构 token。
- 修改 `tests/_v070_frontend_architecture_original.py`，让 CI 浏览器阶段的机械断言跟随 marker 选择，不固定旧文件通配符。
- 修改 `.github/workflows/ci.yml` 和 `.github/workflows/ui-v062.yml`，把浏览器作业标识为 T-PROJECT 阶段并按 `-m playwright` 选择；保留现有安装 Chromium、短期日志和无发布行为。
- 修改 `.github/workflows/build-integrated-runtime.yml`，在调用 `verify.bat` 时同时要求 Node 和 Playwright，继续只上传短期 Artifact，不写回仓库。

### 明确不改

- `AGENTS.md`、`requirements/dev.lock`。
- 产品源码、Playwright 测试行为正文（除统一浏览器路径接线）、真实配置、运行数据和归档正文。
- 任何 tag、Release、GHCR、分支、索引或 Git 历史。

### 后续授权扩展

- 首次严格 full 证明原 Windows 集成 Python 包未包含已经锁定的 `playwright==1.57.0` 后，用户另行明确授权下载依赖并重建 Windows 集成运行包。
- 扩展范围只包含 `vendor/windows/python-runtime.pack`、`vendor/windows/media-runtime.pack`、`vendor/windows/runtime-manifest.json` 及 `tests/test_integrated_runtime.py` 中对应的固定哈希与大小断言；没有改动 `requirements/dev.lock`，也没有下载浏览器。

## 实施顺序与停止条件

1. 重新冻结 Git 状态、上述目标文件和一层直接消费者；若目标文件出现未知改动，停止并报告，不自动合并。
2. 先更新治理文档、Registry 职责、字段所有权和运维入口，使预期行为有唯一文字承接。
3. 更新 T-DOC 实现和规则夹具，先证明旧直链被拒绝、归档索引仍允许、标准 Skill 根被排除且普通 `SKILL.md` 不被宽泛排除。
4. 新增浏览器探测工具，再接入 Windows 与 Linux/macOS runner；所有新增 Python 调用必须显式使用 `-B -X utf8`。
5. 更新 Playwright 路径接线、结构消费者和 CI marker 选择；不得把 CI 独立作业登记成新测试项。
6. 完成普通验证。出现严格解码错误、工作树落盘、真实网络请求、用户 profile 访问、未知浏览器进程或新增下载需求时立即停止，不猜测编码、不扩大权限。
7. 普通验证通过后，申请严格 T-PROJECT full 的显式授权；未获授权前保持验证结果 `not_run`，不得关闭方案。
8. 严格 full 缺少已有浏览器时记录 `blocked`。解除条件是用户提供可用的既有浏览器路径，或另行明确授权安装/下载；本方案不预先授权后者。

候选实质漂移、出现新的语义决定、需要改动排除文件、需要真实网络或需要改变远端状态时，只申请授权差额。

## 验证、输出与授权停点

检查和方案保存阶段没有运行任何动态验证；以下项目在保存时均为 `not_run`，实施后的实际结果见本节末尾。

### 普通验证

1. T-DOC 规则夹具：

   ```powershell
   .\.runtime\python\python.exe -B -X utf8 -m unittest discover -s SoftwareTesting\doc_consistency -p "test_doc_consistency_rules.py"
   ```

   该命令只创建由夹具拥有并自动清理的系统临时目录；不得产生仓库内缓存。

2. 目标项目 T-DOC：

   ```powershell
   .\.runtime\python\python.exe -B -X utf8 SoftwareTesting\doc_consistency\test_doc_consistency.py --workspace-root .
   ```

   该命令必须保持只读；任何工作树写入均视为验证失败。

3. 受影响 pytest 使用 `scripts/windows/new-test-run.ps1 -Action Create` 创建仓库外 run-id，把 `PYTHONPYCACHEPREFIX` 和 `--basetemp` 指向该 run-id，再以 `-B -X utf8`、`-p no:cacheprovider` 运行：

   ```text
   tests/test_playwright_runtime.py
   tests/test_t_project_isolation.py
   tests/test_integrated_runtime.py
   tests/test_v060_release.py
   tests/test_v070_release.py
   tests/test_v070_frontend_architecture.py
   SoftwareTesting/doc_consistency/test_doc_consistency_rules.py
   ```

   该组普通验证不设置 `BILI_RUN_PLAYWRIGHT`，不启动真实浏览器；输出和最终摘要保留在精确 run-id 下，不自动删除。

4. 以 `-B -X utf8` 运行 `tools/verify_source.py`，并对改动的 Python 文件运行 Ruff `--no-cache`；如环境提供 `sh`，对 `scripts/dev/verify-source.sh` 运行 `sh -n`。这些调用不得安装依赖或创建仓库内缓存。

### 实施后结果

- T-DOC 规则夹具通过；目标项目 T-DOC 通过且为 0 warning。
- 受影响 pytest 最终为 76 passed、2 skipped、2 subtests passed；两个 skip 均为当前 Windows 环境无法创建测试符号链接的条件跳过。源码结构检查、Ruff 和 Git for Windows `sh -n` 均通过。
- 普通验证证据位于仓库外 run-id `20260809T043533Z-e950dafc1724`；其 `results/result.json` 明确保持 strict T-PROJECT full 为 `not_run`。
- 用户随后明确授权 Windows strict T-PROJECT full。首个有效候选 run-id `20260809T044711Z-e9587dd6fb46` 为 `blocked`：已定位现有 `C:\Program Files\Google\Chrome\Application\chrome.exe`，但仓库集成 Python runtime pack 缺少 `playwright` Python 包，浏览器阶段未能启动，后续 pytest、Node 和浏览器断言阶段未执行。
- 两个 runner 实现问题已在最终候选前修复并保留诊断证据：run-id `20260809T044258Z-4ffcc0491b2b` 因 `verify.bat` 混合行尾而为 `inconclusive`；run-id `20260809T044418Z-459979c86282` 因 Windows workspace-root 参数边界和退出码冲突而为 `inconclusive`。修复后定向回归为 33 passed、2 skipped。
- 用户另行授权下载依赖并重建 Windows 集成运行包。构建工作目录为仓库外 run-id `20260809T045709Z-e0ed7dc1442d`；重建后的 Python 包包含 `playwright==1.57.0`，SHA-256 为 `0881ff597471925b7f4f81c088aa0761f17bb2b4b66a0ee77ca9df96307305a5`、大小为 66,009,496 字节；媒体包 SHA-256 为 `8e0c05e358384c43041c3dd14ba64144b937b35be1302db152ab48a56815f17f`、大小为 39,154,656 字节。外层清单、两个包的内部逐文件清单、便携 Python、BBDown 和 FFmpeg 冒烟均通过。
- 重建后的第一次 strict run `20260809T050027Z-d45778c9801e` 发现普通 Chrome 受远程调试安全限制影响，在 180 秒握手超时后准确记录为 `blocked`。实现随后补充 30 秒单候选上限和自动候选回退；显式路径仍保持失败即阻断。诊断 run-id `20260809T050510Z-d83160ba9404` 证明现有 Edge 可完成持久上下文及页面断言。
- 最终 Windows strict T-PROJECT full run-id `20260809T050725Z-1957aa89432f` 为 `passed`、退出码 0，实际选择 `C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe`。全量 pytest 为 312 passed、6 skipped、2 warnings，Node 单测 29 项通过；源码结构、Ruff、内置运行时、Node 语法和 Playwright 浏览器阶段均已执行并通过。

### 严格 T-PROJECT full 停点

- 保存方案或普通实施授权均不自动授权全量测试。
- 取得明确授权后，Windows 规范入口必须同时设置 `BILI_VERIFY_REQUIRE_NODE=1` 和 `BILI_VERIFY_REQUIRE_PLAYWRIGHT=1` 后执行 `verify.bat`；T-DOC 仍按协议单独运行。
- full 会在仓库外创建并保留 run-id，启动本次直接拥有的 Python、BBDown、FFmpeg、Node 和无头浏览器进程，并把 profile、缓存、日志、pytest basetemp 和 `results/result.json` 放入 run-id。
- 不启动应用服务、用户浏览器或容器，不访问真实配置、数据库、Cookie、媒体或外部网络。
- 找不到既有浏览器时结果为 `blocked`；不得在该停点自动下载。测试失败、阻断或证据不完整时方案不得关闭。
- Linux/macOS full、远端 CI 和正式认证保持 `not_run`，除非用户另行明确加入；不能用 Windows 结果冒充跨平台或正式认证。

### 输出与清理

- T-DOC 结果通过标准输出保留在任务报告中；规则夹具临时目录由夹具自身精确清理。
- pytest 和 T-PROJECT 输出默认保留在带双层所有权标记的仓库外 run-id。
- 本方案不授权删除 run-id、测试根、浏览器安装、缓存或其他仓库外内容。后续如需清理，必须重新验证所有权并取得精确授权。

## 授权边界

| 动作 | 当前状态 |
| --- | --- |
| 保存本待确认方案及对应待办 | 已由用户明确授权并完成 |
| 修改确定实施范围内文件 | 已由用户明确授权并实施 |
| 普通验证及仓库外受控 run-id | 已由实施授权覆盖并通过 |
| 严格 T-PROJECT full、无头浏览器进程 | 已由用户另行明确授权并完成；最终 run-id `20260809T050725Z-1957aa89432f` 为 `passed` |
| 安装或下载浏览器、依赖或其他资产 | 用户已精确授权下载锁定依赖并重建 Windows 集成运行包；已完成且未下载浏览器 |
| 删除测试输出或其他文件 | 未授权；关闭时只允许方案列明的仓库内精确生命周期移动与条目删除 |
| commit、push、PR、发布、工作流派发 | 未授权且不属于本方案完成条件 |

## 完成条件与生命周期收尾

### 主责完成证明

- 活动运维文档不再复制完整验证命令，也不直接链接归档正文。
- T-DOC 规则夹具证明全部活动 Markdown 的归档入口限制，以及七类标准 Skill 根的精确排除。
- Registry 仍只有 T-DOC 与 T-PROJECT；T-PROJECT 文档、字段、runner 和 CI 消费者一致声明 Playwright 为内部必需阶段。
- Windows 非严格入口有阶段跳过时写 `inconclusive`；严格入口缺少浏览器时写 `blocked`；只有全部必需阶段完成才写 `passed`。
- 新浏览器探测没有下载、安装、用户 profile 复用、真实网络或按名称结束进程能力。
- T-DOC、普通受影响验证和经明确授权的严格 Windows T-PROJECT full 均得到可判定成功证据。
- `AGENTS.md` 原有工作区修改保持不变，最终差异只包含本方案确定范围和生命周期文件。

### 关闭时的状态消费者

- `docs/已知问题与待做需求.md`：删除本待办条目。
- 本方案：从 `docs/方案/DOC-GOV-20260809-文档生命周期与T-PROJECT浏览器测试收口.md` 精确移动到 `archive/docs/plans/DOC-GOV-20260809-文档生命周期与T-PROJECT浏览器测试收口.md`。
- `archive/docs/README.md`：登记一次归档方案、历史职责和当前承接真源。
- `archive/docs/plans/README.md`：登记已完成方案并维持历史入口语义。
- T-DOC：在关闭后再次核对活动待办、活动方案、归档登记和链接。

上述精确仓库内移动和待办删除只在完成条件满足、后续实施授权已经覆盖收尾时执行；保存本方案不授权提前关闭。

### 关联方案、共享文件与对方职责状态

不适用。当前没有其他活动待办或活动方案；`AGENTS.md` 的既有修改属于用户工作区状态，不是关联方案，也不由本方案接管。

### 联合只读复核触发条件

不适用。没有关联活动方案；最终只复核本方案入口、所有者、确定切片、列明的一层消费者，以及修改路径新产生的一跳直接链接或消费者，不递归重做产品事实或测试设计审计。

### 验收停点

- 用户已明确授权并完成严格 Windows T-PROJECT full，最终结果为 `passed`。
- 所有关闭条件均已满足；Linux/macOS、远端 CI 和正式认证仍按范围保持 `not_run`，不阻止本方案关闭。
- 不要求 commit、push、PR、远端 CI 或正式认证作为关闭前提。

### 关闭边界与未运行验证

- Linux/macOS full、远端 CI、真实 Docker、正式认证、产品事实核对和测试充分性审计均不属于关闭证明。
- 最终报告必须逐项列出实际运行、结果、输出位置和仍为 `not_run` 的项目，不能把完成条件预写成结果。

## 最终范围与漂移复核

普通任务只复核：

1. `README.md`、`docs/README.md`、`SoftwareTesting/README.md`、Registry 和两个测试项入口的最终所有者与实际链接；
2. 本方案“确定实施范围”列出的文件；
3. 已列明的一层消费者；
4. 本次修改路径新产生的一跳直接链接、导入或自动化调用。

不得递归扫描全部产品源码、全部测试正文、全部历史或远端配置。出现未列目标文件、额外浏览器下载、真实网络、产品语义变化、测试项新增、状态 schema 变化或发布能力变化时，视为候选实质漂移并停止。

## 评审与残余

- 用户选择的评审轮数：2。
- 实际完成的静态评审轮数：2。
- 最终用户决定：Playwright 不单独登记，归入 T-PROJECT full。
- 集合对账：冻结检查中的活动验证入口、归档直链、T-DOC Skill 根边界、Playwright 归属、旧结构消费者和既有 `AGENTS.md` 修改均有明确处置，没有遗漏或重复。
- 保留残余：未核对产品事实和测试充分性；普通验证与 Windows strict T-PROJECT full 已通过；Linux/macOS、远端 CI 与正式认证仍为 `not_run`，不在完成证明中。
