# DOC-GATE-COMPAT-20260803：T-DOC 标准资产与源码检查兼容方案

- 状态：已完成
- 主责边界：项目文档骨架的标准 T-DOC 资产一致性，以及项目源码检查器与该资产之间的结构机械兼容。
- 授权说明：保存方案本身不等于获得施工、命令、Git、关闭或发布授权；本项后续施工、普通验证、验收和关闭均由用户分别授权。

## 1. 施工前证据

- 项目采用标准骨架路线，[T-DOC 入口](../../../SoftwareTesting/doc_consistency/README.md)和[测试 Registry](../../../docs/软件测试.md)仍分别承担门禁说明与选择职责，不需要迁移目录、Registry schema 或 suite。
- 目标项目中的 [`test_doc_consistency.py`](../../../SoftwareTesting/doc_consistency/test_doc_consistency.py) 与 `project-doc-skeleton/assets/SoftwareTesting/doc_consistency/test_doc_consistency.py` 字节不一致；标准资产新增了“活动方案必须由其自身待办条目实际链接”的精确归属判断。
- 目标项目中的 [`test_doc_consistency_rules.py`](../../../SoftwareTesting/doc_consistency/test_doc_consistency_rules.py) 与对应 Skill 标准资产字节不一致；标准资产比项目副本多一项反例夹具，用于拒绝由其他待办条目代链活动方案。
- 当前 Skill 标准 T-DOC 已直接只读检查目标项目并通过，结果为 0 warning；标准资产规则夹具 27 项通过。因此现有活动文档无需为同步资产而调整内容或导航。
- [`tools/verify_source.py`](../../../tools/verify_source.py) 会把 T-DOC 检测器源码中用于识别 Linux 用户目录的正则字面量误判为真实构建机绝对路径；该检查器已对自身检测规则源码作同类豁免，但尚未对 T-DOC 检测器作精确处理。
- `DOC-GATE-COMPAT-20260803` 在当前文件、归档和可发现 Git 历史中均未发现既有使用。

## 2. 目标

1. 使项目内两份通用 T-DOC 源码与当前 `project-doc-skeleton` 标准资产逐字节一致，不建立项目分叉。
2. 使项目源码边界检查能够区分 T-DOC 检测规则源码与真实绝对本地路径，同时保持其他活动源码和文档继续受现有规则约束。
3. 保持现有文档目录、导航、待办状态模型、Registry、suite、SAFETY 和 UPDATE 实施事项不变。

## 3. 选项与用户决定

### 3.1 T-DOC 资产处理

- 选项 A：按标准骨架路线，把项目内两份 T-DOC 源码整文件同步为当前 Skill 标准资产。
- 选项 B：保留项目旧副本，并重新证明其属于必要的项目专用分叉。
- 推荐：A。项目已经选择标准骨架，标准资产能无告警检查当前项目，现有差异只表现为项目副本遗漏更严格的待办归属规则及夹具，没有项目特例证据。
- 用户决定：选择 A。

### 3.2 源码检查误报处理

- 选项 A：只把 `SoftwareTesting/doc_consistency/test_doc_consistency.py` 登记为绝对路径规则源码的精确扫描豁免；其他文件继续使用现有扫描规则。
- 选项 B：放宽全项目绝对路径正则或豁免整个 T-DOC 目录。
- 选项 C：修改 Skill 标准资产以规避目标项目检查器。
- 推荐：A。它与检查器已有的自身规则源码豁免语义一致，影响面最小，也不会把项目专用限制反向写入通用 Skill。
- 用户决定：选择 A。

## 4. 保存阶段路径

| 动作 | 路径 | 说明 |
| --- | --- | --- |
| 修改 | `docs/已知问题与待做需求.md` | 登记唯一待确认待办并由该条目直接链接本方案 |
| 新增 | `docs/方案/DOC-GATE-COMPAT-20260803-T-DOC标准资产与源码检查兼容方案.md` | 保存集中方案，不进入施工状态 |

## 5. 后续施工路径

以下是获得再次施工授权后才能修改的确认路径：

| 动作 | 路径 | 边界 |
| --- | --- | --- |
| 整文件同步 | `SoftwareTesting/doc_consistency/test_doc_consistency.py` | 与当前 Skill 对应标准资产逐字节一致，不作项目化改写 |
| 整文件同步 | `SoftwareTesting/doc_consistency/test_doc_consistency_rules.py` | 与当前 Skill 对应标准资产逐字节一致，不作项目化改写 |
| 最小修改 | `tools/verify_source.py` | 仅增加 T-DOC 检测器源码的精确豁免，不放宽其他路径扫描 |
| 修改 | `docs/已知问题与待做需求.md` | 施工开始时把本待办转为“实施中” |
| 修改 | 本方案 | 记录授权、实施证据和实际验证状态 |

## 6. 条件关闭路径

只有用户验收并另行授权关闭后，才允许移除活动待办入口，将本方案移动到 `archive/docs/plans/`，并更新 `archive/docs/plans/README.md` 与 `archive/docs/README.md`。这些是条件路径，不是当前保存或施工阶段的确定修改路径。

## 7. 动作边界

- 不修改 `project-doc-skeleton` Skill、标准资产来源或其他 Skill。
- 不修改文档目录、导航结构、Registry schema、测试类别、suite、SAFETY、CI、发布 workflow 或 UPDATE 方案。
- 不核对产品事实，不评价测试覆盖经济性，不执行全项目安全认证。
- 不安装依赖，不启动产品，不访问真实数据，不联网；Git、commit、push、PR、发布和关闭分别授权。
- 不覆盖工作区已有修改。施工前必须重新读取全部确认路径；发现与当前方案冲突的用户修改时暂停相应路径。
- 两份 T-DOC 必须整文件同步并进行字节比较，不使用片段补丁替代标准资产。

## 8. 完成条件

- 项目内两份 T-DOC 源码与施工时当前 Skill 对应资产逐字节一致。
- 标准资产新增的待办归属规则和反例夹具在项目副本中存在，且当前活动方案仍由各自待办条目直接链接。
- 项目源码检查器不再把 T-DOC 检测器中的规则字面量报告为真实绝对路径，同时仍检查其他适用文件。
- 当前文档目录、导航、Registry、suite、SAFETY、UPDATE 事项及产品代码没有因本项发生迁移或语义修改。
- 用户验收并另行授权关闭前，本待办和方案保持活动状态；保存或施工完成均不自动取得关闭授权。

## 9. 验证要求

- 测试层级：普通验证。
- 验证影响域：两份标准 T-DOC 源码、待办与方案直接归属规则、T-DOC 自测试、目标项目文档门禁，以及源码边界检查对检测规则源码的精确豁免。
- 具体验证项：逐字节比较两份目标源码与施工时当前 Skill 资产；运行目标项目中的 T-DOC 规则夹具和目标门禁；运行项目源码边界检查；静态确认豁免仅覆盖 T-DOC 检测器源码，且未改变 Registry、suite、SAFETY、UPDATE 事项或其他扫描范围。未获得命令授权前动态结果保持 `not_run`。

## 10. 当前授权状态

- 已获得按选项 A 保存本方案和待办链接的文件修改授权。
- 已获得按本方案施工的文件修改授权，以及两份标准资产的本地整文件复制命令授权。
- 已获得普通验证命令及源码检查器内部只读 `git ls-files` 枚举授权。
- 已获得用户验收、关闭本待办以及执行关闭后最终 T-DOC 的授权。
- 未获得真实 Git 索引修改、commit、push、PR、发布或产品进程授权。

## 11. 当前实施状态

- 两份 T-DOC 已从当前 Skill 标准资产整文件复制到目标路径；SHA-256 比较均一致，目标哈希分别为 `6CF42DA26279A8BA01B7DAC196F852D855B2EAA81D829CD9048CC498F649170B` 和 `E11DA839658EF7DF2D242894BF107D4E80E60806B8C02EEB29A3F907E734B438`。
- 源码检查器已增加仅覆盖 `SoftwareTesting/doc_consistency/test_doc_consistency.py` 与其自身规则源码的显式豁免集合，其他绝对路径扫描条件保持不变。
- T-DOC 规则夹具 27 项通过，目标门禁通过且为 0 warning，项目源码边界检查通过。
- 用户已验收并授权关闭；活动待办入口已移除，本方案已归档并退出当前施工入口。
- 关闭后的最终 T-DOC 在本方案归档与索引更新完成后执行，实际结果在本次任务交付中报告，以确保验证对象是最终文档状态。
