# TASK-CANCEL-20260823：任务实时状态与预检取消一致性修复方案

- 待办 ID：TASK-CANCEL-20260823
- 状态：已完成
- 形成日期：2026-08-23
- 方案来源：用户在任务中心看到任务仍为下载中，但点击取消收到“任务已结束，无法取消”
- 决策状态：用户已确认独立登记、同批先修、真实取消阶段和幂等重复取消语义
- 实施授权：用户已授权按本方案实施，并于 2026-08-24 单独授权 Playwright 浏览器验证；不包含真实 BBDown/Bilibili、真实下载、完整 T-PROJECT、全量测试、正式认证、commit、push、PR 或发布
- 实施前置：用户明确授权按本方案实施；实施前重新检查工作区和精确目标文件，发现重叠修改时停止覆盖并报告
- 关联方案：本项是 PERF-20260823 的第一切片和正确性前置，但可独立实施、验证和关闭
- 文档门禁关联：DOC-TEST-GOV-20260820 承接当前 T-DOC 的两条归档索引基线失败；本项不越权修复，但关闭前必须由该待办消除全局基线

测试层级：普通定向验证，加用户单独授权的隔离 Playwright 浏览器行为验证。完整 T-PROJECT、真实下载、真实 Bilibili 网络请求和正式认证仍未授权。
验证影响域：OwnedTaskQueue 通知计数、完整任务 SSE、运行中取消阶段、取消 API 幂等、BBDown 信息预检终止、任务中心单卡更新，以及任务生命周期的当前需求、设计和字段契约。
具体验证项：定向 pytest、定向 ruff、Node test、实际 OwnedTaskQueue 的 SSE 工作量断言、T-DOC、Markdown 链接检查和 git diff --check；浏览器、真实下载和完整 T-PROJECT 仍需另行授权。

## 1. 目标与完成结果

本方案同时修复截图现象的确定根因和预检取消的真实生命周期缺口：

1. 实际运行的 OwnedTaskQueue 每次状态通知以及每次有效阶段或进度变化都递增变更计数，恢复 SSE 按变化推送；
2. 运行中任务收到取消后继续保持活动状态，phase 明确为 cancelling，只有执行真正停止后才进入 cancelled 终态；
3. 同一取消请求可以安全重复，不因第一次请求已设置取消事件而产生冲突；
4. 排队任务仍可立即取消并直接进入终态；
5. 清晰度预检中的 BBDown 信息进程能够响应取消；同步元数据网络请求期间保持“正在取消”或“正在暂停”，返回后立即终止后续步骤，不虚构严格总时限；
6. 若取消与任务自然结束发生竞争，前端刷新为服务端最新终态，不继续展示已失真的下载中卡片。
7. 暂停使用独立的 pausing/paused 阶段，不再借用“正在取消”或依赖错误文案表达当前意图。

完成结果必须证明“UI 活动状态、API 返回、SSE 推送和工作线程是否停止”四者一致，不能只修改提示文案。

## 2. 已冻结事实与根因

### 2.1 截图与运行版本

截图中的构建前缀为 7548f3a39785，与 launcher/current-build.json 的当前构建一致；该构建已经包含历史提交 879b35d 的任务页性能优化。因此问题不是旧前端仍在使用轮询，而是优化链路中的实际队列契约没有成立。

### 2.2 SSE 变更计数与通知回归

- AppState 创建的是 OwnedTaskQueue，而不是基类 TaskQueue。
- TaskQueue._notify_locked 会递增 _change_count。
- OwnedTaskQueue._notify_locked 完全覆盖基类方法，只执行拥有者公开 payload 的持久化回调，没有递增 _change_count。
- /api/events 只有在 library 与 export 两个队列的 change_count 变化时才重新查询和推送。
- TaskQueue._set_progress 与 TaskQueue._set_phase 只更新内存字段，不调用 _notify_locked；因此即使修复 OwnedTaskQueue 覆盖问题，下载百分比、速度、ETA 和阶段变化仍不会主动推进变更计数。

因此实际队列的计数长期保持 0：连接首帧从 -1 变为 0 后可以发送，后续任务运行、完成和失败都可能不再产生事件。页面保留旧的“下载中”，而取消 API 查询到任务已经终止，于是返回“任务已结束，无法取消”。只修复覆盖方法仍不足以恢复完整实时行为，还必须让有效阶段和进度变化进入同一通知契约。

只读诊断已经确认同一次通知后 TaskQueue 计数为 1，而 OwnedTaskQueue 计数仍为 0。现有测试只覆盖基类状态计数和伪造 SSE 计数，既没有以实际 OwnedTaskQueue 贯通通知与事件，也没有断言阶段或进度变化会通知。

### 2.3 预检取消缺口

运行管线在 quality_check 阶段依次调用：

- fetch_video_metadata：同步 httpx 请求，既有超时为 12 秒；
- run_bbdown_info：生产路径使用 subprocess.run，最长可等待 120 秒。

取消事件只在这些调用前后检查。正式下载 run_bbdown 已有 cancel_event 和进程树终止能力，但预检信息进程没有复用该能力。因此即使修复 SSE，预检期间也可能长时间停在旧阶段；真实语义应是“取消已接受，正在等待或终止当前操作”，而不是立即声称已取消。

## 3. 目标生命周期与 API 契约

### 3.1 状态与阶段

任务状态 status 保持现有集合，不新增数据库或 API 状态：

| 场景 | status | phase | finished_at | 可用动作 |
| --- | --- | --- | --- | --- |
| 排队中 | queued | queued | null | 暂停、取消 |
| 运行中 | running | 当前执行阶段 | null | 暂停、取消 |
| 已接受运行中暂停 | running | pausing | null | 查看日志；重复暂停安全返回同一意图 |
| 已接受运行中取消 | running | cancelling | null | 查看日志；重复取消安全返回同一意图 |
| 执行确认暂停 | cancelled | paused | 当前时间 | 继续、编辑后重试、删除 |
| 执行确认停止 | cancelled | cancelled | 当前时间 | 重试、删除 |

cancelling 的 phase_label 固定为“正在取消”，pausing 的 phase_label 固定为“正在暂停”，paused 的 phase_label 固定为“已暂停”。pausing 与 cancelling 都属于活动任务；活动计数、历史清理和普通用户活动任务上限继续按 status=running 处理。

暂停仍使用现有独立语义。暂停请求可以复用底层停止机制，但内部调用必须显式传入 pause 意图：运行期间使用 pausing，真正停止后使用 paused。新快照不再依赖错误文案识别暂停；既有 status=cancelled、phase=cancelled 且暂停文案明确的旧快照继续兼容读取，不批量静默改写。不得把普通取消误装成暂停，也不得让 pausing 或 cancelling 卡片暴露继续操作。

### 3.2 取消幂等与竞争

1. 首次取消运行中任务：设置既有 cancel_event，原子写入 phase=cancelling、清理速率与 ETA、更新时间和“正在取消”文案，返回 200 及最新任务。
2. 取消同一仍为 running/cancelling 的任务：保持已设置事件，不重复创建执行或错误终态，返回 200 及同一最新任务。
3. 对已经由取消进入 cancelled 的任务重复取消：返回 200 及当前 cancelled 任务，保证客户端重试幂等。
4. 对 success、failed、skipped 或暂停终态发起取消：保持 409，但客户端必须立即获取或应用服务端最新状态，不保留旧活动卡片。
5. 排队任务取消：从 pending 移除并立即进入 cancelled，返回 200。
6. 取消与自然结束竞争时，以锁内已提交的终态为准；不允许从终态退回 cancelling。

批量取消逐项使用同一契约，部分任务已经终止时刷新对应项，不以一项竞争失败阻止其他活动任务取消。

### 3.3 暂停意图与兼容

1. TaskQueue 的内部停止入口接收显式 pause 或 cancel 意图，但不新增公开 status、数据库列或 API 请求字段；
2. 排队暂停立即进入 status=cancelled、phase=paused；运行中暂停先进入 status=running、phase=pausing，底层停止后再进入 paused；
3. 同一 pausing 请求可以重复，普通取消到达时可以把尚未终止的 pausing 意图升级为 cancelling；反向不得把取消降级为暂停；
4. _finish 的内部阶段覆盖必须在最终通知和持久化之前完成，避免先推送 cancelled 后再补写 paused；
5. 服务端判断新暂停任务只使用 phase，旧快照才允许使用既有暂停文案兼容；前端沿用同一优先级。

### 3.4 预检取消

- run_bbdown_info 新增可选 cancel_event。生产路径改用与 run_bbdown 一致的可控子进程与进程树终止机制，并返回 cancelled=true；信息模式仍保留 MAX_INFO_OUTPUT_CHARS 的 1,000,000 字符容量，不得退化为普通下载日志的 12,000 字符尾缓冲。
- 注入 runner 保持现有测试兼容；调用前和返回后检查 cancel_event，支持取消能力的 runner 可以显式声明并接收该事件。
- Queue 在元数据读取前检查取消；同步网络请求进行期间保持 phase=cancelling 或 phase=pausing，请求返回后立即结束任务，不再启动 BBDown 信息进程。现有 httpx timeout=12.0 是连接、读取、写入和连接池等操作超时，不是严格的 12 秒总截止时间；本方案不承诺绝对上限。
- BBDown 信息进程运行期间收到停止请求时终止进程树，清理预检结果并按意图进入 cancelled 或 paused，不继续创建工作目录或启动正式下载。
- 任何停止终态都通过现有 _finish 路径产生一次最终通知和日志，finished_at 只在此时写入。

本方案不引入后台遗留线程来伪装即时取消，也不通过缩短全局网络超时改变弱网成功率。

### 3.5 SSE 正确性

- TaskQueue 和 OwnedTaskQueue 对“每次 _notify_locked 恰好递增一次计数”遵守同一契约；
- OwnedTaskQueue 继续向持久化回调提供脱离内部 namespaced key 的公开 payload；
- 没有持久化回调时仍递增计数；
- TaskQueue._set_phase 和 TaskQueue._set_progress 在展示字段有效变化后调用同一通知入口；没有字段变化时不产生空通知；
- 高频进度只递增轻量计数，现有 SSE 一秒轮询负责合并，运行中快照持久化继续受现有一秒写入节流保护；
- 一个实际 OwnedTaskQueue 状态变化必须使 /api/events 下一轮重新计算并发送；
- 无变化时仍保持现有只发 keepalive、不全量查询的性能边界。

## 4. 精确实施范围

| 文件 | 计划改动 |
| --- | --- |
| app/progress.py | 增加 cancelling、pausing 与 paused 阶段显示名 |
| app/queue.py | 让有效阶段和进度变化进入通知契约；停止入口接收内部 pause/cancel 意图；把 cancel_event 传入预检；保持终态只由实际停止提交 |
| app/owned_queue.py | 恢复与基类一致的变更计数，同时保留拥有者公开 payload 回调 |
| app/bbdown.py | 为 run_bbdown_info 增加取消事件和生产子进程树终止路径；流式帮助器按调用方保留信息输出容量 |
| app/task_extensions.py | 显式传递暂停意图，收口取消幂等、paused 新旧兼容和终态竞争返回 |
| web/assets/app/pages/tasks-impl.mjs | 显示 cancelling、pausing 与 paused，关闭冲突动作，处理 409 后的最新状态同步 |
| tests/test_queue.py | 覆盖有效阶段/进度通知、运行中取消与暂停阶段、终态提交、重复操作和基类计数 |
| tests/test_v060_task_ownership.py | 以实际 OwnedTaskQueue 覆盖计数、公开 payload、SSE 推送和取消 API |
| tests/test_bbdown.py | 覆盖信息预检进程的取消、超时、1,000,000 字符容量和注入 runner 兼容 |
| tests/frontend/tasks-page.test.mjs | 以纯函数覆盖 cancelling/pausing/paused 分类、动作可用性和终态竞争决策；真实 DOM 更新留给另行授权的 Playwright |
| docs/需求文档.md | 明确正在取消的用户可观察行为和重复取消 |
| docs/设计文档.md | 记录实际队列通知、SSE 变更门控和预检取消链路 |
| docs/字段契约.md | 明确 status=running 下 cancelling/pausing、status=cancelled 下 cancelled/paused、旧暂停快照兼容与 finished_at 规则 |
| CHANGELOG.md | 在未发布章节记录最终实际修复 |

不计划修改数据库 schema、任务 status 枚举、任务 ID、权限模型、下载产物提交逻辑、搜索或媒体库页面。app/task_ownership_api.py 的现有完整 SSE 代码以集成测试证明为主；若实现幂等竞争响应必须改变其错误 envelope，或需要新增字段，视为协议漂移并先申请授权差额。

## 5. 实施顺序

1. 只读复核目标文件、工作区重叠修改和两个关联方案的职责边界。
2. 先写 OwnedTaskQueue 计数回归测试和实际 SSE 集成测试，使截图根因可稳定复现。
3. 修复通知计数和有效阶段/进度通知，确认无回调、有回调、公开 payload、无效更新不通知和有效更新每次恰好加一。
4. 冻结 cancelling、pausing、paused、意图升级和取消幂等单元测试，再修改 Queue 与 task_extensions。
5. 让 run_bbdown_info 接入 cancel_event，同时保留信息输出容量，并覆盖生产进程、超时和注入 runner。
6. 修改任务页显示与竞争刷新，只更新目标任务卡，不引入全页重建。
7. 更新需求、设计、字段契约和 CHANGELOG。
8. 执行第 6 节授权范围内的普通验证。
9. 完成条件满足后独立关闭本项，再继续 PERF-20260823 的其余性能切片。

## 6. 验证方案与副作用边界

保存方案阶段不运行实施验证。获得实施授权后，普通验证至少包含：

1. 定向 pytest：tests/test_queue.py、tests/test_v060_task_ownership.py 和 tests/test_bbdown.py；
2. 定向 ruff：本方案修改的 Python 文件与测试；
3. Node test：tests/frontend/tasks-page.test.mjs 及 TaskStream 既有回归；
4. 文档一致性规则、Markdown 链接检查和 git diff --check。

关键断言固定为：

- OwnedTaskQueue 在无 callback 和有 callback 两种情况下，每次通知的 change_count 都只增加 1；
- 阶段、百分比、速度、ETA 或进度文案有效变化会推进计数，无字段变化不推进；SSE 一秒轮询仍只合并为最多一帧；
- SSE 建连首帧后，运行、进度、cancelling/pausing 和 cancelled/paused 的实际变化均可被观察；空闲轮次不调用 _list_records；
- 运行中首次和重复取消均返回成功且 task ID 不变，finished_at 在实际停止前为 null；
- 排队取消立即终态；已取消重试取消保持成功；暂停使用 pausing/paused，取消可以升级尚未结束的暂停意图；其他终态竞争刷新到真实状态；
- BBDown 信息预检收到事件后返回 cancelled=true，生产测试替身确认进程树终止函数被调用，长信息输出仍按 MAX_INFO_OUTPUT_CHARS 保留；
- 元数据调用尚未返回时任务按意图保持 running/cancelling 或 running/pausing，返回后不再启动 info 或 download；
- 前端 cancelling/pausing 卡片保留日志入口、没有冲突动作，paused 终态恢复继续入口；真实浏览器验证确认最终事件只替换该卡片。

普通验证只使用临时目录、伪造 runner、本地 TestClient 和纯 Node 逻辑测试，不访问 Bilibili、不启动产品服务、不读取真实任务或媒体数据。真实 DOM 节点身份与事件绑定只在另行授权的 Playwright 阶段验证，不在无 DOM 运行时中伪造完成证明。

Playwright 产品浏览器、真实 BBDown、真实 Bilibili 元数据请求、真实下载、完整 T-PROJECT、全量测试和正式认证必须另行授权。用户最终手工验收建议复用隔离任务：预检时取消后先看到“正在取消”，实际停止后变为“已取消”，不再出现页面仍下载中但服务端已经结束的矛盾。

## 7. 完成条件与生命周期关闭

只有同时满足以下条件才可关闭：

- 确定根因由回归测试覆盖，OwnedTaskQueue 的计数契约恢复；
- 任务页、取消/暂停 API、SSE 与工作线程对 running/cancelling/pausing/cancelled/paused 给出一致结果；
- info 预检可以响应停止请求，同步元数据等待期间不伪报终态或严格总时限；
- 暂停、重试、删除、所有权隔离和 SSE 空闲零查询没有回归；
- 第 6 节普通验证全部通过，未授权项目明确记录为未运行；
- 最终差异没有超出第 4 节，没有凭据、真实数据、运行日志或下载产物进入仓库。

获得实施授权并满足完成条件后，关闭动作包括记录实际结果、从活动待办移除本项、将本方案移动到 archive/docs/plans、更新两级归档索引并运行最终文档一致性检查。PERF-20260823 不会随本项自动关闭，只能把本项完成事实作为其前置证据。

关闭不推定 commit、push、PR、发布、安装、下载依赖或任何远端写入。

## 8. 风险、停点与回退

- 双重计数风险：OwnedTaskQueue 不能在自身递增后又通过基类路径重复递增；测试固定为每次加一。
- 终态回退风险：取消线程晚到时不能覆盖 success、failed 或 skipped；所有状态提交都在既有锁内裁决。
- 暂停混淆风险：暂停使用取消事件只是实现细节，公开 phase、文案和可用动作必须保持暂停语义。
- 子进程泄漏风险：预检取消必须复用已验证的进程树终止策略，不能只终止父进程。
- 信息输出截断风险：可取消流式帮助器必须由信息模式传入 MAX_INFO_OUTPUT_CHARS，不能复用普通日志的默认 12,000 字符上限。
- 网络不可抢占风险：元数据请求沿用既有分操作超时但没有严格总时限，等待期间明确展示 cancelling 或 pausing；若要改成异步可抢占 HTTP 或硬总截止时间，属于新的架构决定。
- 共享文件风险：PERF 后续也会修改任务实时 API 与测试；必须先完成本项正确性基线，再落 summary 性能分支。
- 工作区冲突：目标文件存在他人重叠修改时停止，不覆盖、不回退。
- 回退只触及本方案明确拥有且未重叠的精确改动，不使用破坏性 Git 命令或宽泛删除。

## 9. 收尾与联合复核实例

- 本方案主责与完成证明：OwnedTaskQueue 通知计数、取消生命周期、预检终止和任务页一致性；由定向测试和隔离验收证明。
- 覆盖与残余：覆盖截图根因、阶段/进度实时通知、暂停意图与预检取消；不覆盖全站缓存、Dashboard 摘要流、动态加载、强制中断同步 HTTP 或数据库迁移。
- 确定切片与就绪证明：计数回归先行，其次取消状态、预检进程和前端；每层先有失败用例再实施。
- 关闭时的状态消费者：活动待办、活动方案、归档两级索引、需求、设计、字段契约、CHANGELOG 和 PERF 关联说明。
- 关联方案、共享文件与对方职责状态：本项负责完整任务事件正确性；PERF 只在此基线上增加 summary 模式和页面租约；DOC-TEST-GOV 负责消除关闭前的全局 T-DOC 基线。
- 联合只读复核触发条件：本项准备关闭、PERF 开始修改任务实时 API，或共享测试出现职责交叉时。
- 最终范围与漂移复核：新增 status、数据库字段、异步 HTTP 架构或真实数据验证都属于漂移。
- 验收停点：产品浏览器、真实下载、完整 T-PROJECT、全量测试、新协议字段、强制中断同步 HTTP 或硬总截止时间必须等待额外授权。
- 关闭边界与未运行验证：普通定向验证可以随实施授权执行；其他项目必须按第 6 节保留实际状态。

## 10. 保存时基线

- 新待办 ID 在活动文档和可发现仓库内容中没有重名；
- 用户截图、当前构建标识、源代码调用链和只读计数诊断已经支持根因判定；
- 保存前工作区已有 CONTEXT.md、本待办文档及 DOC-TEST-GOV-20260820 方案的修改或未跟踪内容，本任务不覆盖这些已有内容；
- 本方案只记录只读调查、用户确认决定和方案 review，不构成修复完成证明；
- 保存与 review 阶段未运行产品、业务实现测试、浏览器、安装、下载或远端操作；
- 已运行 Markdown 链接检查，结果为 1 passed；git diff --check 通过；
- 已运行 T-DOC，新方案自身无新增问题；全局仍有 BBDOWN-20260815 与 TASKS-20260815 两条归档索引基线失败，由 DOC-TEST-GOV-20260820 承接。

## 11. 2026-08-24 实施记录

- 已完成队列通知、暂停/取消意图、终态提交和前端动作分类：有效公开变化只通知一次，持久化回调完成后才发布变更计数；运行中使用 `pausing/cancelling`，实际停止后使用 `paused/cancelled`，暂停可升级为取消且重复取消幂等。
- 已将 `cancel_event` 接入 `run_bbdown_info` 的生产流式进程路径和可选注入 runner，沿用进程树终止策略并保留 `MAX_INFO_OUTPUT_CHARS`；同步元数据返回后先检查停止事件。跨平台真实子进程测试同时固定了短 ASCII 输出在编码探测结束时必须排空的契约。
- 已完成基类队列、OwnedTaskQueue、任务拥有者 API、完整 SSE、同步元数据等待、信息预检、长输出、前端阶段/动作分类和历史暂停快照兼容的定向测试；Python、ruff 与 Node 普通验证均已执行，最终收口结果以本次任务交付说明为准。
- 已更新[需求文档](../../../docs/需求文档.md)、[设计文档](../../../docs/设计文档.md)、[字段契约](../../../docs/字段契约.md)和根 `CHANGELOG.md` 的当前事实。
- 用户授权后已运行 `tests/test_v070_tasks_playwright.py`：2 项通过；浏览器事件验证确认 `cancelling` 与最终 `cancelled` 只替换目标任务卡，未变化卡片保持同一 DOM 节点，并确认 full/summary SSE 模式切换时最多一个活动连接、零租约时连接关闭、登出完成清理。
- `DOC-TEST-GOV-20260820` 已完成并消除既有 T-DOC 基线；关闭前当前工作区 T-DOC 通过，0 warning。
- 未运行真实 BBDown/Bilibili、真实下载、完整 T-PROJECT、全量测试或正式认证；未执行 commit、push、PR 或发布。
- 本项完成条件均已满足，已从活动待办退出并归档；`PERF-20260823` 继续独立关闭。
