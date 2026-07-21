# 更新日志

本项目遵循语义化版本号。

## 0.7.0 - 2026-07-21

- 将前端切换为浏览器原生 `.mjs` ES Modules 和静态 import，不引入 npm、打包器或生产 Node 依赖；
- 建立单一 API client、Session/Context store、generation-safe Router、Modal、Toast、Confirm、SearchableSelect 和 TaskStream；
- Dashboard、Download、Search、Library、Groups、Tasks、Users、Account、Settings 和 More 全部迁移为正式 `mount()`/幂等 `dispose()` 页面；
- Search 保持当前页请求、本地标题筛选、最多预载下一页和路由竞态取消；Library 保持筛选、标签、批量操作、改分组、Range 播放和续播；
- Dashboard 与 Tasks 共享唯一 EventSource，反复进入退出页面不会创建重复 SSE、重复事件或重复请求；
- 删除旧 `app.js`、全部 `enhancements-*` renderer/overlay、Legacy Bridge、`browser-version.js` 和版本专用 CSS 覆盖；
- 最终入口收口为 `qrcode.min.js`、唯一 `app/main.mjs` 和 tokens/base/components/pages 四层 CSS；
- 版本检查合入 App Shell，浏览器资源与服务版本不一致时提供重启服务和强制刷新提示；
- 构建指纹加入 `.mjs`，Windows/Linux 自检加入全部 `.js/.mjs` 语法和依赖无关 Node tests；
- 新增最终架构、页面生命周期、竞态、请求计数、五档 Playwright、Windows 和 Docker 发布门禁；
- 数据库继续为 schema v4，不修改下载算法、API 协议、权限矩阵、标签业务模型或持久化目录。

## 0.6.2 - 2026-07-20

- 统一桌面端按钮、输入框和下拉框的普通高度为 40px，移动端触控控件保持不低于 44px，并压缩过大的页面留白和下载输入区域；
- 用户显示名、临时密码和分组重命名不再调用浏览器 `prompt`，统一使用站内 Modal；
- 账号页将 Bilibili 扫码/Cookie 与网站账号、改密和最多 10 个有效 Token/登录设备拆成独立页签；
- 用户、分组等动态选项超过 8 个时提供带搜索框的两列选择列表，清晰度和编码等固定少量选项继续使用普通下拉框；
- 设置页默认只展示常用配置，任务超时、轮询和编码策略收纳到高级设置折叠区；
- 新增 V0.6.2 静态回归、Playwright 交互和五档固定视口门禁，不修改下载、数据库、API 或权限模型。

## 0.6.1 - 2026-07-20

- 修复本机 V0.5 schema v2 数据库中 `users` 表为空时，V0.6 任务所有权迁移因找不到管理员而回滚的问题；
- 迁移这类旧库时在同一事务内创建受限临时管理员，强制首次改密，并把既有任务和导出归属该管理员；
- 保留迁移前一致性备份、事务回滚、外键检查和远程默认密码限制。

## 0.6.0 - 2026-07-20

- 将后端搜索收敛为唯一 `/api/search` 路由，固定读取 Bilibili 当前页 20 条原始结果；
- 将精准/模糊改为浏览器当前页标题二级筛选，切换模式或筛选词不再访问网络；
- 首次只加载当前页，空闲时最多预加载下一页 1 页，并用 `AbortController` 阻止旧请求覆盖新结果；
- 增加 10 分钟 WBI 密钥缓存、3 分钟原始搜索页缓存和签名失效单次重试；
- 搜索响应直接合并标签、下载状态和删除状态，停用搜索页 overlay 与额外标签批量请求；
- 修正搜索控件、批量栏和 768px 竖屏平板断点，并用 Playwright Chromium 验证五个固定视口；
- CI 增加 Playwright、SQLite/userdata 迁移、Windows/Docker 静态检查和 Markdown 内部链接门槛；
- 所有运行模式改为网站账号登录；Windows 回环全新安装创建受限临时管理员，Docker/NAS 保留一次性初始化令牌；
- `users`、`sessions` 和审计 schema 升级，迁移前自动备份 SQLite、事务迁移、外键检查并只保留最近 3 份备份；
- 每次登录创建独立 HttpOnly Token，数据库只保存哈希；每用户最多 10 个有效会话并按最近连接时间淘汰；
- 增加强制首次改密、当前 Token/CSRF 轮换、本人设备会话管理以及管理员普通用户 API；
- 数据库升级到 schema v4，新增正式 `task_records` 和任务/导出所有者迁移，v3→v4 不重复撤销有效会话；
- 普通用户下载被强制为当前设备导出，任务、日志、SSE 和导出文件按 `owner_user_id` 隔离；
- 设备导出内部按用户命名空间隔离，允许不同用户同时导出同一个 BV；
- 普通用户活动任务最多 10 个，终态任务保留 7 天且最多 100 条；管理员终态任务最多 500 条；
- 管理员任务 API 增加用户、状态、目标、关键词、排序和按用户分组查询；
- 普通用户导航收敛为“下载”和“任务”，管理员新增响应式用户管理和按用户筛选/分组的任务中心。

## 0.5.6 - 2026-07-18

- Windows x64 集成可移植 Python 3.13.14、锁定依赖、BBDown 和 FFmpeg，`git pull` 后直接运行 `start.bat`；
- Docker 默认拉取 GHCR 的 amd64/arm64 预构建镜像，同时保留 `BUILD_LOCAL=true` 的本机构建后备；
- 持久化目录调整为 `config/`、`userdata/`、`downloads/`；
- SQLite、任务快照、下载索引、任务日志、缓存和临时文件统一放入 `userdata/`；
- 清理根目录和过期发布工具并归档历史版本报告。

## 0.5.5 - 2026-07-18

- 将 GitHub `main` 恢复为直接可审查源码树，删除 Base64、临时隧道和 Actions 源码恢复链路；
- 固化 `.default` 配置模板与缺失字段自动补全；
- 保持可配置 IP/端口、QNAP 持久化、媒体库、分组、设备导出和网页扫码登录。

## 0.5.4 - 2026-07-18

- 修复 Windows 慢网络依赖安装和源码自检问题；
- 修复可信 Host 与局域网访问配置；
- 加强监听主机名校验。

## 0.5.3 - 2026-07-18

- 重建为可直接克隆的标准 Git 仓库；
- 固化 `.default` 配置模板与增量升级；
- 明确 Windows、局域网、域名和 QNAP Docker 的监听及持久化边界。

## 0.5.2 - 2026-07-18

- 修复远端缺少完整可审查源码树；
- 配置改为模板与实际文件分离；
- 增加更新、网络配置和仓库恢复校验。

## 0.5.0 - 2026-07-17

- Windows 本地运行与 QNAP/NAS Docker 部署；
- 下载前清晰度预览和实际码流展示；
- 媒体库、分组、在线播放、Range、续播和设备导出；
- 管理员认证、CSRF、可信 Host/代理、安全 Cookie、审计日志和 Bilibili 扫码登录。
