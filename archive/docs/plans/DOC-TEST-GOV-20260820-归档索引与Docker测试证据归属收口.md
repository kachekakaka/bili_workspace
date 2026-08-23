# DOC-TEST-GOV-20260820：归档索引与 Docker 测试证据归属收口方案

- 待办 ID：`DOC-TEST-GOV-20260820`
- 状态：已完成
- 形成日期：2026-08-20
- 方案来源：项目文档骨架检查发现的两项收口问题
- 实施授权：用户于 2026-08-24 明确授权实施本方案；实施前已复核工作区和精确目标，唯一共享修改 `docs/字段契约.md` 属于同批次已知变更并已合并保留
- 关闭结果：目标改动与普通验证均已完成，真实 Docker、完整 T-PROJECT、T-LAUNCHER、全量测试、正式认证和远端 CI 未运行
- 活动方案目录所有权：保存本方案前 `docs/方案/` 不存在，本次保存为精确创建；方案退出活动区后，仅在该目录为空且仍可确认由本任务创建时删除该空目录

测试层级：普通验证；只覆盖文档骨架、共享测试证据帮助器及其直接消费者，不运行全量测试、正式认证或真实 Docker 构建。
验证影响域：`archive/docs/README.md` 的归档完整性，`T-PROJECT`/`T-DOCKER` 运行证据契约，Python 与 PowerShell 证据帮助器，Docker 本地手工验证入口，以及对应的静态和单元测试。
具体验证项：定向 `pytest`、定向 `ruff`、PowerShell 临时目录冒烟、T-DOC 规则自检与当前工作区门禁、Markdown 链接检查和 `git diff --check`；关闭活动方案后再运行一次最终 T-DOC，所有结果按实际运行状态记录。

## 1. 目标与完成结果

本方案把一次文档骨架检查中确认的两个问题收口为一组可独立实施、可验证、可关闭的变更：

1. 让 `archive/docs/README.md` 完整登记现存归档正文，消除“二级计划索引已登记、归档根索引漏登记”的结构不一致；
2. 将 `docs/运维/Docker镜像打包与离线交付.md` 中的真实本地 Docker 验证正式定义为现有 `T-DOCKER` 的手工执行入口；
3. 让共享运行证据能够稳定回答“这次运行属于哪个 Registry 测试项”，避免 Docker 验证继续产出只能被解释为 `T-PROJECT` 的证据；
4. 保留既有证据的可读、可记录边界，不把本次收口扩大为工作流改造、真实 Docker 验证或产品代码变更。

完成后，归档根索引、活动测试 Registry、测试项说明、帮助器契约、运维手册和结果文件对同一事实给出一致答案。任何未实际运行的验证都必须明确保留为未运行，不以静态检查替代动态结果。

## 2. 已冻结事实与问题判定

### 2.1 归档根索引漏项

以下归档正文存在，且已经由 `archive/docs/plans/README.md` 登记，但没有出现在规范归档入口 `archive/docs/README.md`：

- `archive/docs/plans/BBDOWN-20260815-Windows启动器BBDown子进程缺陷修复.md`；
- `archive/docs/plans/TASKS-20260815-任务页性能优化.md`。

`CHANGELOG.md` 已承接这两项完成事实的当前版本历史，因此根索引中的“当前承接真源”统一指向 `CHANGELOG.md`，不恢复历史方案为活动入口。

### 2.2 Docker 手册与证据身份不一致

当前 Docker 运维手册实际执行镜像构建、运行、保存和重新加载，并通过 `scripts/windows/new-test-run.ps1` 创建运行目录和写入 `results/result.json`。与此同时：

- `SoftwareTesting/docker/README.md` 只列出 CI workflow 消费者，没有声明这份本地手工入口；
- `scripts/README.md`、`docs/字段契约.md` 和现有帮助器把运行证据描述为 `T-PROJECT` 证据；
- 运行标记和结果没有稳定的 Registry 测试项 ID，无法从证据自身区分 `T-PROJECT` 与 `T-DOCKER`。

因此问题不只是缺少一条链接。若只改文案，Docker 结果仍然没有可机读的测试归属；若直接把现有 schema 解释为通用格式，又会改变旧证据语义而没有兼容边界。本方案选择显式演进证据契约。

## 3. 目标契约

### 3.1 归档登记契约

在 `archive/docs/README.md` 增加且仅增加以下两份正文的规范登记：

- `BBDOWN-20260815`：历史职责描述 Windows 启动器 BBDown 子进程缺陷修复与验收记录，当前承接真源为 `CHANGELOG.md`；
- `TASKS-20260815`：历史职责描述 SSE 按变更推送、前端差量渲染及性能验收记录，当前承接真源为 `CHANGELOG.md`。

不移动、重写或重新激活两份历史方案，也不在活动待办中为它们创建新任务。

### 3.2 证据 schema 与测试项身份

目标契约固定如下：

1. 测试根标记 `.bili-workspace-test-root.json` 继续使用 `schema_version: 1`。它只证明仓库外测试根及项目归属，不绑定单一测试项，因为同一测试根可以容纳多个测试项的独立运行；
2. 新创建的运行标记 `.bili-workspace-test-run.json` 和结果 `results/result.json` 使用 `schema_version: 2`；
3. schema v2 在现有字段基础上新增必填字符串 `test_id`，其值必须是活动测试 Registry 的稳定 ID；本方案使用的合法值为 `T-PROJECT` 和 `T-DOCKER`；
4. 一个运行目录只属于一个 `test_id`。创建、校验和记录结果时必须核对传入身份与运行标记一致，身份不一致时拒绝写入；
5. Python 帮助器 `tools/t_project_isolation.py` 保持 `T-PROJECT` 专用定位及现有 CLI 调用方式，对新运行固定写入 `test_id: T-PROJECT`；
6. PowerShell 帮助器 `scripts/windows/new-test-run.ps1` 明确为 Registry 运行证据的共享 Windows 入口，`Create` 与 `Record` 都要求显式 `-TestId`，并校验 Registry ID 的基本格式及前后一致性；
7. 已存在的运行标记或结果 schema v1 继续可读。它们只按旧语义解释为隐式 `T-PROJECT`；记录既有 v1 运行时只接受 `T-PROJECT`，保留 v1 结构，不把旧证据静默改写为 v2，也不允许 `T-DOCKER` 依附 v1 运行；
8. 新建运行一律写 v2，不提供创建新 v1 证据的开关。未知 schema、缺失身份、非法 ID 或身份不匹配均明确失败。

本次不新增 Registry 测试项。Docker 本地手工验证是现有 `T-DOCKER` 的另一执行路径，不创建 `T-DOCKER-MANUAL` 等派生身份。

### 3.3 T-DOCKER 本地手工入口

`SoftwareTesting/docker/README.md` 与 Docker 运维手册建立双向关系：

- 测试项说明登记 CI workflow 消费者和本地手工运维入口，说明二者均受 `T-DOCKER` 的 `affected_only`、真实 Docker 副作用和证据语义约束；
- 运维手册在执行前链接 `T-DOCKER` 测试项说明，并使用 `-TestId T-DOCKER` 创建运行和记录结果；
- 手册保留真实构建、运行、保存、加载的现有步骤，不在本方案实施时实际执行这些步骤；
- `passed` 只能在手册列明的必要阶段实际成功后记录，跳过或失败不得写成通过。

## 4. 精确实施范围

| 文件 | 计划改动 | 完成判据 |
| --- | --- | --- |
| `archive/docs/README.md` | 增加 `BBDOWN-20260815` 与 `TASKS-20260815` 两行规范登记 | 两份现存归档正文各在根索引出现一次，链接可解析，当前承接真源指向 `CHANGELOG.md` |
| `SoftwareTesting/PROTOCOL.md` | 明确运行证据必须绑定 Registry ID，新建证据使用 v2 | 协议能区分测试根归属、运行身份和旧证据兼容语义 |
| `SoftwareTesting/SAFETY.md` | 补充共享测试根下按运行隔离及 `test_id` 一致性要求 | 安全规则不再把运行证据隐式限定为单一测试项 |
| `SoftwareTesting/project/README.md` | 声明 Python 帮助器固定产生 `T-PROJECT` v2 证据及 v1 兼容边界 | 项目自检入口与帮助器实际行为一致 |
| `SoftwareTesting/docker/README.md` | 登记 Docker 运维手册为 `T-DOCKER` 本地手工入口和证据消费者 | CI 与本地手工路径的职责、触发和副作用边界清晰 |
| `docs/字段契约.md` | 将运行标记与结果字段契约演进为 v2，并记录 v1 兼容规则 | `test_id` 必填性、允许值来源、拒绝条件和旧证据语义完整 |
| `docs/运维/Docker镜像打包与离线交付.md` | 接入 `T-DOCKER` 说明，并在创建和记录时显式传入 `T-DOCKER` | 手册产出的新证据可以从文件自身识别为 `T-DOCKER` |
| `scripts/README.md` | 区分共享 PowerShell 帮助器与 T-PROJECT 专用 Python 帮助器 | 脚本入口职责与参数要求可发现 |
| `scripts/windows/new-test-run.ps1` | 增加 `TestId` 参数、v2 写入、身份校验及 v1 兼容分支 | 新证据含稳定身份；错误身份和不匹配写入失败；旧 v1 行为受限且可解释 |
| `tools/t_project_isolation.py` | 新运行固定写入 `T-PROJECT` v2；读取和记录保留受限 v1 兼容 | 现有 CLI 消费者无需改参，新旧契约均有显式测试 |
| `tests/test_t_project_isolation.py` | 更新新建证据断言，增加 v1 兼容、未知 schema 和身份错误用例 | Python 帮助器的主路径及兼容边界均被覆盖 |
| `tests/test_repository_layout.py` | 更新对 PowerShell 参数、身份校验和文档接线的静态约束 | 共享脚本和 `T-DOCKER` 手册关系不能无声退化 |

以下直接消费者在目标契约下保持现状，只纳入复核，不计划改动：

- `scripts/dev/verify-source.sh` 与 `scripts/dev/run-playwright-phase.sh`：继续调用 T-PROJECT 专用 Python CLI，调用参数不变；
- `.github/workflows/ci.yml` 与 `.github/workflows/docker-image.yml`：仍是既有 `T-DOCKER` workflow 消费者，本方案不改变触发、权限或执行逻辑；
- `docs/软件测试.md`：继续保留唯一 `T-DOCKER` Registry 行，不新增测试 ID；
- 产品源码、Dockerfile、Compose 配置及版本文件：不在影响范围内。

如实施时发现新的直接 schema 消费者、必须更改 workflow 才能成立，或上述“不改动”文件需要语义改写，视为候选实质漂移，停止并申请授权差额，不自行扩大范围。

## 5. 实施顺序

1. 只读复核工作区状态、待办与方案一一对应关系、ID 唯一性，以及全部精确目标文件；若目标文件存在不属于本任务的重叠修改则停止；
2. 先补齐归档根索引两行，使确定性结构问题独立收口；
3. 更新测试协议、安全规则和字段契约，先冻结 v2、`test_id` 与 v1 兼容语义；
4. 更新 Python 与 PowerShell 帮助器，不改变 Python 现有 CLI 消费者的调用方式；
5. 更新 T-PROJECT、T-DOCKER、脚本入口和 Docker 运维手册，使文案与实现接线一致；
6. 更新定向测试，检查预期变更中没有生成物、凭据、真实用户数据或运行现场；
7. 按第 6 节顺序执行普通验证，逐项记录命令、结果和未运行项；
8. 仅在完成条件全部满足且没有授权差额时，执行第 7 节的生命周期关闭动作并运行关闭后的最终 T-DOC。

## 6. 验证方案、顺序与副作用

保存方案阶段不执行实施验证；仅对已跟踪的待办差异运行一次 `git diff --check` 作为写入卫生机械核对，退出码为 0。该命令不覆盖未跟踪的新方案文件，也不作为实施完成证明；其余动态项目统一为 `not_run`。获得实施授权后按以下顺序重新执行完整验证：

1. 定向 Python 测试：

   ```text
   python -B -X utf8 -m pytest -q -p no:cacheprovider tests/test_t_project_isolation.py tests/test_repository_layout.py tests/test_markdown_links.py
   ```

2. 定向静态检查：

   ```text
   python -B -X utf8 -m ruff check --no-cache tools/t_project_isolation.py tests/test_t_project_isolation.py tests/test_repository_layout.py
   ```

3. PowerShell 冒烟：在系统临时目录下创建一个带 GUID 的全新、精确路径，分别验证 `T-PROJECT` 和 `T-DOCKER` 的 Create/Record v2 正常路径，验证错误 `TestId`、记录时身份不匹配、未知 schema 及 `T-DOCKER` 绑定 v1 会失败。仅清理由本次冒烟创建、且可通过精确路径和标记确认所有权的临时目录；所有权无法确认时保留并报告，不宽泛删除；
4. T-DOC 标准规则自检：

   ```text
   python -B -X utf8 SoftwareTesting/doc_consistency/test_doc_consistency_rules.py
   ```

5. 当前工作区 T-DOC：

   ```text
   python -B -X utf8 SoftwareTesting/doc_consistency/test_doc_consistency.py --workspace-root .
   ```

6. 差异卫生检查：

   ```text
   git diff --check
   ```

7. 待办退出、方案归档和索引登记完成后，再运行一次第 5 项作为最终活动/归档状态验证。

普通验证的允许副作用只包括 Python 缓存被 `-B`/`--no-cache` 抑制后的最小进程运行，以及第 3 项明确新建的临时测试目录。不得启动产品服务、读取真实数据、使用凭据、访问私有资源、修改远端状态或产生费用。

以下验证明确排除，除非用户另行授权：真实 Docker build/run/save/load、完整 `T-PROJECT`、`T-LAUNCHER`、全量测试、正式认证、远端 CI、产品进程、真实业务数据、安装或下载依赖。未运行这些项目不阻止本方案按限定影响域关闭，但必须在关闭记录中列明。

## 7. 完成条件与生命周期关闭

只有同时满足以下条件，才可将本方案视为完成：

- 归档根索引完整登记两份漏项，且没有把历史正文恢复为当前入口；
- 新建运行证据具备可机读 `test_id`，Python 路径固定归属 `T-PROJECT`，Docker 手工路径固定归属 `T-DOCKER`；
- v1 兼容边界、拒绝条件和未知 schema 行为在实现、文档与测试中一致；
- `T-DOCKER` 说明与 Docker 运维手册双向接线，Registry 仍只有一个 `T-DOCKER`；
- 第 6 节授权范围内的普通验证全部通过，或未运行项按既定边界明确记录；
- 最终差异没有超出精确实施范围，没有凭据、真实数据、构建产物或测试现场进入仓库。

在已确认方案的实施授权下，满足完成条件后按同一次授权执行以下关闭动作：

1. 把本方案实际状态和验证结果写入方案；
2. 从 `docs/已知问题与待做需求.md` 删除本待办；
3. 将本文件完整移动到 `archive/docs/plans/`，不在活动目录保留副本；
4. 在 `archive/docs/plans/README.md` 登记已完成计划；
5. 在 `archive/docs/README.md` 登记本方案历史职责，当前承接真源指向相应现行测试治理入口；
6. 若 `docs/方案/` 已空、仍可确认由本次任务创建且没有他人文件，再精确删除该空目录；
7. 运行关闭后的最终 T-DOC，确认活动待办、活动方案和归档正文的一一对应关系。

方案保存本身不触发上述动作，也不授权 commit、amend、push、PR、发布、安装、下载或任何远端写入。

## 8. 风险、停点与回退

- **旧证据误迁移风险**：不得把 v1 文件原地补字段或改版本；兼容读取与新写入分支保持分离；
- **身份伪造风险**：基础格式校验不能替代 Registry 治理；文档固定 ID 来源，测试覆盖未知或不匹配身份，实施时不扩展成自动解析 Markdown Registry 的新机制；
- **帮助器职责漂移风险**：Python 工具继续专属于 `T-PROJECT`，共享能力只落在 PowerShell 入口和公共字段契约；
- **通过状态失真风险**：帮助器只记录调用方给出的状态，Docker 手册必须保留“全部必要阶段成功后才可 passed”的约束；
- **用户修改冲突**：任一精确目标出现重叠修改时停止，不覆盖、不回退；
- **动态验证失败**：保留现场与失败输出，状态维持未完成，不执行生命周期关闭；修复若超出本方案则申请新增授权；
- **回退边界**：实施中只回退本任务明确拥有且未与他人修改重叠的精确变更；不使用 `git reset --hard`、`git checkout --` 或宽泛删除。保存阶段若用户决定放弃，只在明确授权后删除本待办和活动方案，并在符合所有权条件时删除空目录。

## 9. 收尾与联合复核实例

- 本方案主责与完成证明：主责是归档根索引完整性、运行证据测试项身份、T-DOCKER 本地手工入口接线；以精确差异、定向测试、PowerShell 冒烟、T-DOC 和链接检查结果证明。
- 覆盖与残余：覆盖第 4 节列出的文档、帮助器和测试；不覆盖真实 Docker/QNAP 验收、完整项目自检、启动器、远端 CI 和正式认证，这些保持原治理状态。
- 确定切片与就绪证明：归档漏项和证据身份属于同次文档骨架检查，但可按第 5 节先后独立落地；实施就绪要求方案已确认、工作区目标无冲突且无新增 schema 消费者。
- 关闭时的状态消费者：`docs/已知问题与待做需求.md`、`docs/方案/`、`archive/docs/plans/README.md`、`archive/docs/README.md` 与 T-DOC 是关闭状态消费者，必须在同一关闭序列保持一致。
- 关联方案、共享文件与对方职责状态：两份漏登记历史方案均已完成，只补规范索引；`DOCKER-QNAP-20260806` 等历史方案只作背景证据，不恢复授权、不改状态；当前没有其他活动关联方案。
- 联合只读复核触发条件：若实施发现其他活动方案、未登记归档正文或新增证据 schema 消费者，先做联合只读复核并报告，不继承授权或自动扩大施工。
- 最终范围与漂移复核：关闭前逐项对照第 4 节文件清单和“不改动”清单；任何 workflow、产品源码、Docker 配置、版本或外部状态变化均视为漂移。
- 验收停点：本方案不要求用户手工产品验收；但出现新语义决定、目标冲突、真实 Docker 必要性、验证升级或授权差额时必须停下等待用户决定。
- 关闭边界与未运行验证：普通验证通过且限定完成条件满足即可关闭；真实 Docker、全量测试、正式认证、远端 CI 和产品进程默认未运行，并在最终记录中明确列出，关闭不推定 Git 或发布动作。

## 10. 保存时基线

- 待办 ID 在活动区、归档区和可发现 Git 历史中未发现重名；
- 保存前工作区 `git status --short --untracked-files=all` 为空；
- 保存前 `docs/方案/` 不存在；
- 保存阶段未运行测试或项目门禁，结果均为 `not_run`；仅对已跟踪的待办差异执行了 `git diff --check`，退出码为 0，未覆盖未跟踪的新方案文件；
- 本节只记录保存方案时已完成的只读调查与机械基线，不作为实施完成证明。

## 11. 2026-08-24 实施与验证记录

- 已在归档根索引补登 `BBDOWN-20260815` 与 `TASKS-20260815`，保持历史正文冻结并统一由 `CHANGELOG.md` 承接当前事实。
- 仓库外测试根标记继续使用 schema v1；新运行标记与结果改用 schema v2 并要求 `test_id`。T-PROJECT 专用 Python 帮助器固定写入 `T-PROJECT`，共享 PowerShell 帮助器的 Create/Record 均要求显式 `-TestId` 并校验身份一致。
- schema v1 运行继续只按隐式 `T-PROJECT` 校验和记录，结果保持 v1 且不补写身份；未知 schema、v2 缺失或错误身份、记录身份不匹配以及 `T-DOCKER` 绑定 v1 均明确失败。
- 已将 Docker 镜像打包手册与现有 `T-DOCKER` 双向接线；本地手工路径使用 `-TestId T-DOCKER`，Registry 未新增测试项，真实 Docker 阶段未在本次实施中运行。
- 定向 pytest：`21 passed, 1 skipped`；跳过项为当前 Windows 环境不允许创建测试符号链接的既有平台条件。定向 Ruff：通过。
- PowerShell GUID 临时目录冒烟：T-PROJECT/T-DOCKER v2 Create/Record 正常路径通过；非法 ID、v2 身份不匹配、未知 schema 与 T-DOCKER 绑定 v1 均按预期失败；T-PROJECT v1 记录保持 v1。执行环境的删除策略拦截了后续清理，因此已确认所有权的临时根 `C:\Users\73839\AppData\Local\Temp\bili-doc-test-gov-5fee8dbb4e2f41d19fb8b8799407cb14` 保留在仓库外并在交付中报告。
- T-DOC 标准规则自检：29 项通过；关闭前当前工作区 T-DOC：通过，0 warning；Markdown 链接检查随定向 pytest 通过；`git diff --check`：通过。
- 未运行真实 Docker build/run/save/load、完整 T-PROJECT、T-LAUNCHER、全量测试、正式认证、远端 CI、产品进程或真实业务数据；未执行 commit、push、PR、发布、安装或下载。
