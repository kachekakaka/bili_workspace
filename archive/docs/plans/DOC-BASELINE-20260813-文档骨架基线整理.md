# DOC-BASELINE-20260813：文档骨架基线整理方案

- 方案状态：已完成；2026-08-13 用户明确要求“实施方案”后执行并关闭
- 形成日期：2026-08-13
- 结构路线：单一上下文项目的标准骨架路线
- 自查：用户要求两轮，已完成两轮
- 施工后反哺报告：不生成
- 测试层级：普通验证
- 验证影响域：项目协作入口、活动与历史文档导航、方案生命周期、测试治理、T-DOC 标准资产及其一层直接消费者
- 具体验证项：标准资产逐字节比较、T-DOC 规则夹具与目标门禁、源码结构检查、定向 Markdown／仓库布局测试、差异检查及生命周期关闭后的最终 T-DOC

## 1. 目标、结果与非目标

本方案把项目文档骨架重新收敛到当前 `project-doc-skeleton` 的标准要求，移除已经由用户明确选择放宽的项目级加严规则，补齐当前标准新增的入口、方案模板和测试资产所有权，同时保留有明确项目决策或产品安全依据的规则。

完成后的用户可感知结果：

1. 文档机械门禁与当前 Skill 标准资产逐字节一致，不再维护项目分叉。
2. 历史正文不再被所有活动文档一律禁止引用；核心导航仍只能把归档索引作为历史入口，归档正文仍不得冒充当前真源。
3. 正式认证按候选影响选择必要全量测试、核对候选身份并形成结构化交接，不再固定要求 CI、界面、Windows、Docker 四类门禁同时存在。
4. 已有 Docker 构建验证取得独立且稳定的测试治理所有者，并仅在影响域命中时进入选择范围。
5. 根入口、方案收尾模板、公开只读联网边界和活动 suite 生命周期与当前骨架一致。

本方案不核对产品行为事实，不评价测试覆盖、断言质量或成本，不修改产品代码、现有 Docker／浏览器／启动器工作流，不恢复正式发布，也不运行 Docker、浏览器、产品进程、全量测试或正式认证。

## 2. 冻结范围与初始证据

### 2.1 文件集合

只读检查冻结了以下结构证据：

- 根协作与用户入口：`AGENTS.md`、`README.md`、`CONTEXT.md`、`CHANGELOG.md`、`SECURITY.md`、`THIRD_PARTY_NOTICES.md`；
- 活动文档：`docs/` 下核心文档、12 份 ADR、运维索引与 5 份运维手册；
- 测试治理：`docs/软件测试.md`、`SoftwareTesting/` 的总入口、协议、安全、三个现有 suite 和 T-DOC 三份资产；
- 生命周期：`docs/已知问题与待做需求.md`、`docs/README.md`、`archive/docs/README.md`、`archive/docs/plans/README.md`；
- 直接消费者：三个活动 workflow、`tools/verify_source.py`、`tools/check_markdown_links.py`、`tests/test_markdown_links.py`、`tests/test_repository_layout.py`；
- 测试资产候选：Git 当前存在的 `tests/`、`launcher/tests/`、`SoftwareTesting/`、测试脚本与 workflow；候选集合包含已跟踪文件和未忽略新文件，检查时工作树没有未跟踪测试资产。

精确排除项目级 Agent Skill 工具资产、无关产品源码、全部测试设计、二进制交付物、真实数据、仓库外运行现场、远端状态和归档正文内容审计。归档正文仅在证明当前承接或已有动态结果归宿时作一层证据使用。

### 2.2 当前状态

- 工作树在检查结束与保存前均为干净状态；实施任务必须重新冻结拟改文件，不能覆盖后来出现的用户修改。
- 项目只有根 `CONTEXT.md`，没有 `CONTEXT-MAP.md` 或嵌套 `CONTEXT.md`，属于单一上下文。
- 当前共有 38 份非归档活动 Markdown；`archive/docs/README.md` 静态登记了当前 33 份归档 Markdown 正文。
- `docs/已知问题与待做需求.md` 保存前没有待办，`docs/方案/` 保存前不存在。
- 保存本方案会创建此前不存在的 `docs/方案/`；该目录由本工作保存阶段创建，方案关闭归档后若为空，可由后续普通实施任务凭本记录和实施授权精确删除。
- 仓库内 `.runtime/` 当前不存在；ADR 0009 已声明旧便携运行链退出。若实施前重新出现，不能删除、忽略或恢复项目特例，须先判断所有权和对标准门禁的影响。
- `.github/workflows/ci.yml` 当前以 `python -B -X utf8` 调用 T-DOC，调用方式与标准资产兼容。

### 2.3 T-DOC 初始字节证据

保存方案前的 SHA-256 如下，三份项目资产均与 Skill 资产不同：

| 文件 | Skill 资产 SHA-256 | 项目资产 SHA-256 | 结论 |
| --- | --- | --- | --- |
| `README.md` | `05C44FCFB2B1D5A1936EFA3CDDDDC1AA3B13134F2B09A5822ADA4B0B3D499C24` | `4714ED12869196F4A4460037FB31316488C858E1A34E4D9812184B766F31B7BE` | 不一致 |
| `test_doc_consistency.py` | `A139C3B9972F8C4B8A2C72D9E125E8C8E1F01E1E3E2A019861619C61B985B6C0` | `9722DE6B7E8816BBA2E7D53D5558853134882CB7DA242F37E31719E51E32D869` | 不一致 |
| `test_doc_consistency_rules.py` | `700348DD492AC585F66AC6AD2C5190433ACB6EF289D0B4976F2E0A3334BF6F2C` | `FD5FD26A4087E37607B4E6F6594FD7CEE6AB38F77A0216A1985E5601AE786E7B` | 不一致 |

## 3. 结构覆盖矩阵

| 维度 | 精确范围 | 状态 | 证据与残余 |
| --- | --- | --- | --- |
| 上下文与路线 | 根上下文、长期入口、所有权与发布节奏 | 已覆盖（满足） | 单一上下文；项目已经采用标准主干与标准测试治理入口 |
| 结构与职责 | 根入口、核心文档、条件专题、测试治理 | 已覆盖（存在缺口） | 固定与条件文件存在；标准资产、顶层所有者和部分职责说明需要同步 |
| 入口与导航 | 协作、用户、文档、测试、ADR、运维、归档 | 已覆盖（存在缺口） | 核心导航与两跳文档路径成立；`launcher/`、`scripts/` 及安全／许可入口需要补齐 |
| 活动与历史生命周期 | 活动文档、归档索引、suite 动态结果 | 已覆盖（存在缺口） | 归档登记完整；历史链接政策过宽，启动器 suite 混入动态运行结果 |
| 待办、方案与记录 | 当前待办、活动方案、检查记录、收尾模板 | 已覆盖（存在缺口） | 保存前无活动项且条件目录不存在；收尾模板缺少当前标准字段 |
| 测试治理结构 | Registry、协议、安全、suite、候选测试资产 | 已覆盖（存在缺口） | 现有三个 Registry 项有入口；Docker 构建验证没有唯一所有者和选择关系 |
| 机械门禁与授权边界 | T-DOC、规则夹具、CI 接线、协作授权 | 已覆盖（存在缺口） | 门禁、自测试和 CI 接线存在；三份资产与当前标准不同，联网分类与确认语义需要收口 |
| 内容事实一致性 | 产品行为、版本、字段与运维事实 | 未覆盖 | 仅确认职责位置，不核对正文真假 |
| 测试设计与经济性 | 覆盖、重复、断言质量和成本 | 不适用 | 不由骨架方案评价或重构 |

## 4. 用户决定

1. 文档机械门禁采用 Skill 标准三份资产，不保留项目兼容分叉。
2. 正式认证采用 Skill 基线，不再固定要求四类平台门禁同时通过。
3. 现有 Docker 构建验证由专门的 Docker 测试项长期负责。
4. Docker 测试项登记为 `affected_only`，只在 Docker、运行依赖或镜像输入受影响时选择。

以上四项均由用户在本次检查中明确选择“按推荐”。方案自查为两轮且已完成；实施后不生成反哺报告。

## 5. 冻结发现与唯一归宿

### F-01：T-DOC 与当前 Skill 标准资产分叉

- 证据：三份文件已完整读取并逐字节哈希比较，均不一致；项目版本额外排除 `.runtime/`、禁止全部活动 Markdown 直链归档正文，且缺少当前标准的非标准顶层 Markdown 所有者规则。
- 影响：项目继续维护自己的门禁语义，无法直接证明与 Skill 标准一致，也会保留用户认为过严的历史链接限制。
- 选项：整文件采用标准资产；或保留项目分叉并手工同步部分规则。
- 推荐与决定：用户已选择整文件采用标准资产。三份文件不得用片段补丁拼接；来源缺失或目标出现新修改时停止。

### F-02：活动与历史链接政策仍按旧加严语义表述

- 证据：`docs/README.md` 把历史材料描述为只可由归档索引承接，当前 T-DOC README 也声明全部活动 Markdown 只能经索引进入历史正文。
- 影响：即使精确历史证据有当前职责，普通活动文档也不能直接引用；与 F-01 的标准门禁决定不一致。
- 选项：继续全面禁止；或只约束核心导航不把归档正文当作当前入口。
- 推荐与处置：依据用户对 F-01 的决定，采用后者；归档索引仍唯一登记历史正文，历史材料仍不得成为当前事实真源。

### F-03：正式认证固定绑定四类平台门禁

- 证据：`SoftwareTesting/PROTOCOL.md` 要求同一候选同时核对 CI、界面、Windows 和 Docker 门禁。
- 影响：与候选无关的平台也会成为认证阻断条件，超过当前 Skill 的必要全量测试、候选身份与结构化交接基线。
- 选项：按候选影响选择必要范围；或保留固定全平台认证。
- 推荐与决定：用户已选择按候选影响选择。全量测试与正式认证仍需明确授权，未覆盖项必须如实记录。

### F-04：Docker 构建验证没有唯一治理所有者

- 证据：`.github/workflows/docker-image.yml` 和 `.github/workflows/ci.yml` 中已有当前 Docker 构建验证；现有 T-PROJECT 只承接源码、Python、Node 与 Playwright，T-LAUNCHER 只承接 Windows 启动器及其下游 Docker 导出。
- 影响：Docker 镜像实际构建的触发、输入、失败语义和结果归属没有稳定活动入口。
- 选项：建立专门 Docker 测试项；或并入项目完整自检。
- 推荐与决定：用户已选择建立专门测试项，不新增 workflow 或构建动作。

### F-05：Docker 验证的完整检查选择关系未声明

- 证据：现有专用 workflow 按 Docker 及镜像输入路径触发，项目完整自检并不执行真实 Docker 构建。
- 影响：无法判断用户要求完整项目检查时是否必须具备 Docker 环境。
- 选项：`affected_only`；或 `full`。
- 推荐与决定：用户已选择 `affected_only`。正式认证可以在候选影响命中时把它纳入必要范围。

### F-06：部分活动 Markdown 缺少直接所有者入口

- 证据：`launcher/RELINKING.md` 与 `scripts/README.md` 所在顶层目录没有从根 README、文档总入口或测试总入口直接链接目录内所有者；`SECURITY.md` 与 `THIRD_PARTY_NOTICES.md` 也没有用户入口。
- 影响：采用标准 T-DOC 后两个顶层目录会被门禁拒绝，安全与许可材料也难以从用户入口发现。
- 选项：退出或归档有效材料；或在根 README 增加最小直接入口。
- 推荐与处置：现有源码检查和构建职责证明这些材料仍活动，采用最小直接入口，不复制正文。

### F-07：活动启动器 suite 混入动态结果

- 证据：`SoftwareTesting/launcher/README.md` 保存 2026-08-13 的试运行结果、未执行项、构建 ID、大小和哈希；相同结果已由归档方案承接，当前规范候选身份由 `launcher/current-build.json` 承接。
- 影响：稳定 suite 职责与一次性运行证据混写，候选更新后容易漂移。
- 选项：继续复制动态结果；或只保留稳定触发、命令、断言与结果语义。
- 推荐与处置：采用后者，删除活动副本而不删除归档证据或当前构建身份。

### F-08：协作、测试安全与方案收尾仍有标准漂移

- 证据：`AGENTS.md` 缺少“回复只确认当前明确问题”的边界和普通验证默认说明；`SoftwareTesting/SAFETY.md` 把所有真实联网一律归为显式项目，与上位协作规则允许有界公开只读联网冲突；`docs/README.md` 的收尾模板缺少覆盖与残余、确定切片与就绪证明、最终范围与漂移复核。
- 影响：普通只读公共依赖获取可能被无差别阻断，方案也难以独立证明范围闭合；较早确认的语义边界不够明确。
- 选项：保留旧规则；或按当前标准补齐，同时保留认证、上传、外部写入、费用、大规模下载、产品进程和真实数据的明确授权。
- 推荐与处置：上位协作规则与标准骨架已唯一裁决，采用后者，不放宽真实数据、进程、删除或外部写入边界。

发现集合为 F-01 至 F-08，共 8 项；本方案逐项承接全部成员，没有遗漏、重复或无归宿项。

## 6. 确定实施范围

### 6.1 协作、用户与文档入口

- `AGENTS.md`：补入当前问题确认语义和普通验证默认边界；保留现有语言、修改授权、Git、删除、秘密、停止发布和不覆盖用户修改规则。
- `README.md`：在主要目录或安全／许可位置直接链接 `scripts/README.md`、`launcher/RELINKING.md`、`SECURITY.md` 和 `THIRD_PARTY_NOTICES.md`；不复制 `docs/README.md` 的专题清单。
- `docs/README.md`：把历史规则收敛为“归档索引统一登记、核心导航不直链正文、精确历史引用不得冒充当前真源”；把任务级收尾模板补齐为当前标准九项。

### 6.2 标准 T-DOC

从当前安装的 `project-doc-skeleton` Skill 资产目录整文件覆盖以下三个目标：

- `SoftwareTesting/doc_consistency/README.md`
- `SoftwareTesting/doc_consistency/test_doc_consistency.py`
- `SoftwareTesting/doc_consistency/test_doc_consistency_rules.py`

不得手工重写、挑选片段或保留 `.runtime/` 项目特例。实施前若 Skill 资产不可用、内容已经变化或目标文件出现用户修改，停止并报告候选漂移。

### 6.3 测试治理

- `docs/软件测试.md`：新增 `T-DOCKER | affected_only`，入口指向 `SoftwareTesting/docker/README.md`，唯一职责限定为当前 Docker 镜像实际构建与非发布边界。
- `SoftwareTesting/README.md`：直接链接新的 Docker suite。
- 新建 `SoftwareTesting/docker/README.md`：记录 Registry 身份、受影响触发、输入、工作目录、现有两个 workflow 消费者、amd64／arm64 与单架构构建边界、公开读取与 Docker 环境副作用、无发布断言、失败语义和清理边界；不保存动态结果。
- `SoftwareTesting/PROTOCOL.md`：正式认证改为必要范围；明确 T-DOCKER 为受影响选择项，不改变 T-DOC 和 T-PROJECT 的 `full` 身份。
- `SoftwareTesting/SAFETY.md`：区分有界公开只读联网与认证、真实数据、外部写入、费用、明显大规模下载及特殊环境；保留测试根、所有权、真实数据、产品进程、浏览器 profile 和精确清理规则。
- `SoftwareTesting/project/README.md`：明确 T-PROJECT 不替代 T-DOC 或 T-DOCKER，完整检查按 Registry 分别选择。
- `SoftwareTesting/launcher/README.md`：明确 T-LAUNCHER 与 T-DOCKER 的职责边界；移除日期、构建 ID、哈希和一次性通过／未执行记录，只保留稳定测试契约。
- `docs/运维/发布与回滚流程.md`：在源码验证入口增加 T-DOCKER 链接，不复制第二套 Docker 验证命令。

现有 `.github/workflows/ci.yml`、`.github/workflows/docker-image.yml` 和 `.github/workflows/launcher.yml` 只作为消费者证据，本方案不修改它们。

### 6.4 生命周期保存与关闭

保存阶段只执行：

- 在 `docs/已知问题与待做需求.md` 登记 `DOC-BASELINE-20260813` 为 `待确认` 并实际链接本方案；
- 创建并保存本方案；不把状态改为 `实施中`。

后续普通任务取得“按已确认方案实施”的明确授权后，才可把待办转换为 `实施中` 并修改目标文件。完成条件满足后：

1. 从活动待办移除 `DOC-BASELINE-20260813`；
2. 把本方案完整移动到 `archive/docs/plans/DOC-BASELINE-20260813-文档骨架基线整理.md`；
3. 在 `archive/docs/README.md` 恰好登记一次，并以 `docs/README.md` 作为当前结构承接；
4. 在 `archive/docs/plans/README.md` 增加已完成计划入口；
5. 若 `docs/方案/` 因移动后为空，依据第 2.2 节的所有权记录精确删除该目录；
6. 对关闭后的最终候选重新运行 T-DOC。

## 7. 明确排除与保留能力

- 不修改 ADR 0002 的停止正式发布决定，不创建 tag、Release 或 GHCR 正式镜像。
- 不修改产品行为、字段、数据库、下载、认证、网络、容器安全或 Windows 启动器契约。
- 不调整 T-PROJECT 的 Node／Playwright 必需阶段，不评价该选择的成本或覆盖价值。
- 不修改 `tools/t_project_isolation.py`、`tools/check_markdown_links.py`、`tools/verify_source.py` 或产品测试实现；它们只作直接消费者与静态验证证据。
- 不迁移测试根、真实运行现场、缓存、`.runtime/` 或仓库外文件；不删除所有权不明内容。
- 不生成施工后反哺报告，不创建额外检查记录、profile、manifest 或评审日志。
- 不执行 commit、push、PR、发布、安装、下载或远端写入。

## 8. 一层直接消费者与漂移边界

| 变更对象 | 已知直接消费者 | 实施要求 |
| --- | --- | --- |
| T-DOC 三份资产 | Registry、`SoftwareTesting/README.md`、`.github/workflows/ci.yml`、`tools/verify_source.py` | 保持现有兼容调用；若消费者需要实质改写，停止并申请范围差额 |
| 历史导航政策 | `docs/README.md`、T-DOC 规则夹具、归档索引 | 只放宽普通活动文档的精确历史引用，不放宽归档登记和核心导航 |
| 正式认证定义 | `AGENTS.md` 授权边界、`SoftwareTesting/PROTOCOL.md`、运维验证入口 | 授权要求不变，实际范围和未覆盖项必须记录 |
| T-DOCKER | 两个现有 workflow、Registry、测试总入口、T-PROJECT、T-LAUNCHER、运维验证入口 | 建立文档所有者与选择关系，不修改现有 workflow |
| 启动器动态结果 | 归档启动器方案、`launcher/current-build.json` | 删除活动副本前确认两个现有承接仍在，不重写历史结果 |
| 活动方案生命周期 | 当前待办、`docs/README.md`、两个归档索引、T-DOC | 关闭时同步移动、登记、移除入口并执行最终门禁 |

普通实施任务只复核本表、确定文件和本次修改路径新产生的一跳直接链接或消费者；不递归扫描整个工作区，不重做产品内容或测试设计审计。

## 9. 实施顺序

1. 重新读取适用 `AGENTS.md`，检查工作树与确定文件是否出现覆盖风险；核对 Skill 资产来源和 `.runtime/` 当前状态。
2. 整文件同步三份 T-DOC 标准资产，不在此时运行门禁。
3. 更新 `AGENTS.md`、根 README 与 `docs/README.md`，先满足标准资产新增的顶层所有者和生命周期语义。
4. 新建 T-DOCKER suite，并同步 Registry、测试总入口、协议、安全、T-PROJECT、T-LAUNCHER 与运维入口。
5. 从 T-LAUNCHER 活动入口移除动态结果副本，静态确认归档方案和当前构建记录仍承接原证据。
6. 执行第 10 节普通验证；失败只按证据修复本方案确定切片，出现新语义、消费者、外部副作用或实质漂移时停止。
7. 完成静态 review 和最终范围复核；满足完成条件后执行第 6.4 节生命周期关闭。
8. 对关闭后的最终状态重新执行 T-DOC，并据实记录最终结果。

## 10. 验证、结果语义与副作用

所有动态验证在方案保存时均为 `not_run`。后续普通任务使用当前项目可用的 Python 3.11 入口，并显式传入 `-B -X utf8`；缺少入口或严格 UTF-8 解码失败时按 `blocked` 或 `failed` 记录，不猜测本地编码或替换字符继续。

### 10.1 标准资产字节比较

使用当前用户目录下安装的 Skill 资产根，对三个同名文件计算 SHA-256；Skill 与项目目标必须逐项相等。哈希比较只读，不创建输出文件。若 Skill 位置或资产身份无法确定，结果为 `blocked`。

### 10.2 T-DOC 规则夹具

```text
python -B -X utf8 SoftwareTesting/doc_consistency/test_doc_consistency_rules.py
```

只使用标准库和系统临时目录；夹具自行清理临时目录，不创建项目测试根或产品进程。

### 10.3 当前项目 T-DOC

```text
python -B -X utf8 SoftwareTesting/doc_consistency/test_doc_consistency.py --workspace-root .
```

只读项目内容；施工中候选和生命周期关闭后的最终候选分别执行，前者不能替代后者。

### 10.4 直接结构消费者

```text
python -B -X utf8 tools/verify_source.py
python -B -X utf8 -m pytest -q -p no:cacheprovider tests/test_markdown_links.py tests/test_repository_layout.py
git diff --check
```

`-B` 禁止默认字节码缓存，pytest 禁用缓存插件；测试只允许使用其自动管理的系统临时目录。出现未预期的项目内或仓库外产物时停止并报告，不用宽泛清理继续。

### 10.5 不运行项目

| 项目 | 保存时状态 | 本方案普通验证中的状态 |
| --- | --- | --- |
| Docker 构建与容器运行 | `not_run` | `not_run` |
| Playwright 与用户浏览器 | `not_run` | `not_run` |
| 产品进程与真实数据 | `not_run` | `not_run` |
| T-PROJECT full | `not_run` | `not_run` |
| T-LAUNCHER 产品／打包验收 | `not_run` | `not_run` |
| 全量测试 | `not_run` | `not_run` |
| 正式认证 | `not_run` | `not_run` |
| 远端 CI 结果核对 | `not_run` | `not_run` |

静态阅读、其他命令通过或计划执行都不能把这些状态改写为 `passed`。

## 11. 授权、停止条件与可恢复性

- 本方案保存不授权实施。后续必须取得“按已确认方案实施”或同等明确授权。
- 该实施授权可覆盖第 6 节确定文件变更、第 10 节普通验证、实际结果记录，以及完成条件满足后的待办退出、方案归档、索引更新和精确空目录清理。
- commit、push、PR、发布、安装、外部写入、费用、明显大规模下载、产品进程、真实数据、全量测试和正式认证仍需单独明确授权；本方案不需要这些动作。
- 若任一确定文件出现未提交用户修改、Skill 资产不可获得或变化、`.runtime/` 重新出现并影响扫描、现有 workflow 需要实质改写、验证升级或发现新的测试资产所有者问题，立即停止，只申请授权或决策差额。
- 所有拟改文件均由当前 Git 历史可恢复；不得用覆盖、重置或宽泛删除处理冲突。

## 12. 完成条件

只有以下条件全部满足，才可关闭本方案：

1. F-01 至 F-08 的确定处置全部落地，且没有新增待决语义。
2. T-DOC 三份目标与当前 Skill 资产逐字节一致。
3. 根入口能够直接发现两个非标准顶层 Markdown 所有者、安全和许可材料。
4. 历史引用、正式认证和公开只读联网规则与用户决定及上位协作规则一致。
5. T-DOCKER 在 Registry、测试总入口和独立 suite 中具有唯一身份，两个现有 workflow 的所有者和 `affected_only` 选择关系明确。
6. T-LAUNCHER 活动入口不再保存日期、哈希或一次性运行结果，已有归档和当前构建身份仍可用。
7. 第 10 节适用普通验证均取得可判定结果；未运行项目保持 `not_run`。
8. 当前待办退出、方案归档、两个归档索引更新、任务创建的空条件目录精确清理完成。
9. 生命周期关闭后的最终 T-DOC 通过，工作树没有本任务产生的未说明副产物。

完成不依赖 commit、push 或 PR，也不能由文件写入完成或中途门禁通过提前推定。

## 13. 收尾与联合复核

- 本方案主责与完成证明：由 F-01 至 F-08 的确定文件差异、标准资产字节一致、T-DOCKER 唯一所有权、适用普通验证和最终生命周期门禁共同证明。
- 覆盖与残余：覆盖文档骨架、导航、生命周期、测试治理与机械门禁；产品内容事实、测试质量／经济性、Docker／浏览器／产品动态验证和正式认证不在范围内并保持原状态。
- 确定切片与就绪证明：第 6 节文件与动作均为确定切片；四项用户决定、初始哈希、Git 感知测试资产集合、直接消费者和条件目录所有权记录提供就绪证据。
- 关闭时的状态消费者：`docs/已知问题与待做需求.md`、`docs/README.md`、`docs/软件测试.md`、`SoftwareTesting/README.md`、两个归档索引和最终 T-DOC。
- 关联方案、共享文件与对方职责状态：没有关联活动方案；归档的 Windows 启动器方案只承接既有动态结果，不继承其授权或结论。
- 联合只读复核触发条件：若实施期间新增与其他活动方案共享的文件或所有者，停止并重新判断；当前不触发跨方案联合复核。
- 最终范围与漂移复核：只复核确定入口与所有者、第 6 节文件、本方案列明直接消费者，以及修改路径新产生的一跳链接；不递归或重做全项目审计。
- 验收停点：普通验证、静态 review、完成条件和生命周期关闭全部满足后方可结束；新语义、验证升级或外部副作用先取得差额。
- 关闭边界与未运行验证：按第 6.4 节归档并执行最终 T-DOC；Docker、Playwright、产品进程、真实数据、全量测试、正式认证、远端 CI、commit、push 和 PR 均不因本方案关闭而发生或被宣称通过。

## 14. 实施结果

2026-08-13 按第 6 节确定切片完成实施，没有修改三个现有 workflow、产品代码或方案排除项，也没有生成施工后反哺报告。

- 三份 T-DOC 目标与 Skill 资产逐字节相等，SHA-256 分别为 `05C44FCFB2B1D5A1936EFA3CDDDDC1AA3B13134F2B09A5822ADA4B0B3D499C24`、`A139C3B9972F8C4B8A2C72D9E125E8C8E1F01E1E3E2A019861619C61B985B6C0`、`700348DD492AC585F66AC6AD2C5190433ACB6EF289D0B4976F2E0A3334BF6F2C`。
- T-DOC 规则夹具通过：29 项测试全部成功；生命周期关闭前的项目 T-DOC 通过，`0 warning(s)`。
- 定向 Markdown 与仓库布局测试使用既有项目 `.venv` 的 Python 3.11.1 执行，结果为 `8 passed`。PATH 中的默认 `python` 缺少 pytest，首次调用结果为 `blocked`，没有安装或下载依赖。
- `tools/verify_source.py` 进入可判定阶段后为 `failed`：唯一命中是 Git 原有 `launcher/tests/test_build_tools.py` 中用于验证扫描器的合成字符串 `SESSDATA=<synthetic-secret-value>`；该文件与 HEAD 无差异，修正校验器或产品测试不在本方案范围，因此保留为既有基线残余。
- `git diff --check` 通过。最终 T-DOC 在待办退出、方案移动、归档索引更新和空条件目录清理全部落地后执行；为保证门禁绑定最终候选，其结果只在本次任务交付中据实报告，不再回写并改变门禁后的候选。
- Docker 构建与容器运行、Playwright、产品进程与真实数据、T-PROJECT full、T-LAUNCHER 产品／打包验收、全量测试、正式认证和远端 CI 均保持 `not_run`；未执行 commit、push、PR、发布、安装或外部写入。
