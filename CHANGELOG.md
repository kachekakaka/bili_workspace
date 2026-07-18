# 更新日志

本项目遵循语义化版本号。

## 0.5.6 - 2026-07-18

- Windows x64 集成可移植 Python 3.13.14、锁定依赖、BBDown 和 FFmpeg，`git pull` 后直接运行 `start.bat`；
- 删除 Windows 首次启动对 PyPI、GitHub Release 和系统 Python 的依赖；
- 集成运行包由 GitHub Windows Runner 从固定官方来源构建，校验上游和成品 SHA-256，并执行冒烟测试；
- 两个运行包均小于普通 Git 的 100 MiB 单文件限制，不要求 Git LFS；
- Docker 默认拉取 GHCR 的 amd64/arm64 预构建镜像，同时保留 `BUILD_LOCAL=true` 的本机构建后备；
- 保持配置模板增量补字段以及 `/data/config`、`/data/media`、`/data/cache`、`/data/tmp` 持久化映射。

## 0.5.5 - 2026-07-18

- 将 GitHub `main` 恢复为直接可审查源码树，删除 Base64、临时隧道和 Actions 源码恢复链路；
- Windows 全新克隆新增 BBDown 官方固定发布包与 PyPI 固定 FFmpeg wheel 的 SHA-256 校验后备；
- 将后续需求、性能优化、配置边界和原始基线包哈希固化到仓库文档；
- 保持配置模板自动补字段、可配置 IP/端口、QNAP 四目录持久化、媒体库、分组、设备导出和网页扫码登录。

## 0.5.4 - 2026-07-18

- 修复 Windows 网络较慢时 `pip` 下载依赖因默认读取超时而中断的问题；
- 修复依赖安装中断后 `.venv` 虽已创建、源码自检却不再补装缺失依赖的问题；
- 修复源码自检仍强制下载 Windows 运行包、Release 资产尚未上传时被 HTTP 404 阻断的问题；
- 修复从 `config/config.json` 设置局域网主机名时，HTTP 可信 Host 未同步导致手机或域名访问被拒绝的问题；
- 加强监听主机名校验，拒绝标签首尾连字符、空标签和超长标签。

## 0.5.3 - 2026-07-18

- 重建为可直接克隆的标准 Git 仓库，移除 bootstrap/Base64 源码恢复流程；
- 固化 `.default` 配置模板与缺失字段自动补全，实际配置、SQLite、任务和分组数据继续保持未跟踪；
- 明确 Windows、局域网、域名和 QNAP Docker 的可配置监听地址与 1–65535 端口；
- 保留 `/data/config`、`/data/media`、`/data/cache`、`/data/tmp` 四类持久化映射；
- 增加需求落实清单、配置目录说明以及仓库恢复/发布校验。

## 0.5.2 - 2026-07-18

- 修复 GitHub 仓库仅包含占位文件和源码归档分段的问题，正式提交可审查、可测试的完整源码树；
- 配置改为 `.default` 模板与实际文件分离，启动和更新时递归补充新增字段而不覆盖用户值；
- 支持旧根目录 `config.json` 自动迁移到 `config/config.json`；
- IP、监听地址和端口可配置，非回环监听自动启用服务器模式和管理员认证；
- Windows 新增 `configure_network.bat` 和 `update.bat`；
- Docker/QNAP 使用四个固定持久化目录，`docker/.env` 从 `.env.default` 自动生成和增量升级；
- 自动化测试扩展到 130 项。

## 0.5.0 - 2026-07-17

- Windows 本地运行与 QNAP/NAS Docker 部署；
- 下载前清晰度预览、最低清晰度硬校验和实际码流展示；
- 可选择、新建、重命名、合并和浏览逻辑分组；
- SQLite 持久化任务、媒体库、用户会话与播放进度；
- 浏览器在线播放、Range 请求、续播和原文件下载；
- NAS 临时下载并导出到当前设备，完整发送后清理临时产物；
- 原文件优先播放，并支持按需生成 H.264/AAC 兼容副本；
- 管理员认证、CSRF、可信 Host/代理、安全 Cookie 与审计日志；
- 网页 Bilibili 二维码登录，凭据仅保存在服务器端。
