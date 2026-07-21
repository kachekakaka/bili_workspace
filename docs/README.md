# bili_workspace 文档索引

当前功能、目录结构和操作方式以“当前主线”文档为准。冻结计划保留在 `plans/` 用于追溯；已被取代的历史资料位于 `archive/`。

> 当前应用版本为 V0.7.0。V0.7.0 前端结构整理 PR 1–8、Windows/Docker 发布验收和自动 tag/Release 流程已进入主线。

## 当前主线

- [V0.7.0 功能与验收](V0.7功能与验收.md)
- [V0.7.0 Release notes](releases/V0.7.0.md)
- [产品需求与架构基线](产品需求与架构基线.md)
- [需求落实清单](需求落实清单.md)
- [账号权限与会话管理](账号权限与会话管理.md)
- [任务所有权与保留策略](任务所有权与保留策略.md)
- [QNAP Docker 部署指南](QNAP_Docker部署指南.md)
- [域名与反向代理配置](域名与反向代理配置.md)
- [备份、恢复与旧版本迁移](备份恢复与V0.4迁移.md)
- [发布、更新与回滚流程](发布与回滚流程.md)
- [源文件与恢复清单](源文件与恢复清单.md)

V0.6.0 功能验收、V0.6.2 UI/UX Review 和 UI 回归清单继续保留，作为兼容与历史验收依据：

- [V0.6.0 功能与验收](V0.6功能与验收.md)
- [V0.6.2 UI/UX Review](UI_UX_REVIEW_v0.6.2.md)
- [UI 问题与回归清单](UI_ISSUES.md)

## 当前目录边界

```text
Windows / 源码：config/、userdata/、downloads/
Docker：/data/config、/data/userdata、/downloads
```

Docker 构建和 Compose 文件位于 `docker/`；根目录只保留 `start.bat`、`update.bat`、`verify.bat` 三个 Windows 用户入口。

## V0.7.0 架构状态

- 唯一应用入口：`web/assets/app/main.mjs`；
- 唯一第三方全局：`window.QRCode`；
- 页面位于 `web/assets/app/pages/`，统一 `mount()` / `dispose()`；
- Core 位于 `web/assets/app/core/`；
- CSS 位于 `web/assets/styles/` 的 tokens/base/components/pages 四层；
- 不存在 Legacy Bridge、`app.js`、`enhancements-*` renderer/overlay、MutationObserver 页面补丁或原生 prompt/confirm；
- TaskStream 在已登录应用中只创建一个 `/api/events` 连接。

## 开发计划状态

V0.7.0 的方案和 Review 是冻结的批准快照，文档内部原始“待实施”标记用于保留 Review 时点；实际实施状态以当前 `main`、PR #26–#33、CI、tag 和 Release 为准。

- [V0.7.0 前端结构整理方案](plans/V0.7.0_前端结构整理方案.md)：PR 1–8 已完成；
- [V0.7.0 方案 Review](plans/V0.7.0_前端结构整理方案_REVIEW.md)：所有冻结门禁已落实；
- [V0.7.0 前端兼容文件清单](plans/V0.7.0_前端兼容文件清单.md)：记录旧文件删除与最终入口。

## 历史资料

历史内容集中在 [`archive/`](archive/README.md)，历史发布报告位于 [`archive/releases/`](archive/releases/)。开发计划状态见 [`plans/`](plans/README.md)。
