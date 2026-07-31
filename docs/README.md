# bili_workspace 文档索引

当前功能、目录结构和操作方式以活动文档为准。当前应用版本为 V0.7.0；V0.7.0 前端结构整理 PR 1–8、Windows/Docker 发布验收和自动 tag/Release 流程已进入主线。

## 长期核心文档

- [需求文档](需求文档.md)
- [设计文档](设计文档.md)
- [已知问题与待做需求](已知问题与待做需求.md)
- [软件测试 Registry](软件测试.md)
- [字段契约](字段契约.md)

核心文档是长期职责入口。兼容迁移期间，既有事实正文保持原样并由核心入口路由；合并、拆分或正文同步留给后续文档一致性审查和语义裁决。

## 当前版本与兼容验收

- [V0.7.0 功能与验收](V0.7功能与验收.md)
- [V0.7.0 Release notes](releases/V0.7.0.md)
- [V0.6.0 功能与验收](V0.6功能与验收.md)
- [V0.6.2 UI 发布与验证](V0.6.2_UI发布与验证.md)
- [V0.6.2 UI/UX Review](UI_UX_REVIEW_v0.6.2.md)
- [UI 问题与回归清单](UI_ISSUES.md)

## 运维

- [部署、网络、备份、恢复、升级与发布入口](运维/README.md)

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

当前没有迁入骨架的活动待办或实施中方案。V0.6.0 与 V0.7.0 已完成方案、Review 和兼容清单保留为历史证据；文档内部原始状态用于保留当时快照，实际完成状态以当前 `main`、PR、CI、tag、Release 和验收文档为准。

## 历史资料

- [文档归档索引](../archive/docs/README.md)
