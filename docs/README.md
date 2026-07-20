# bili_workspace 文档索引

当前功能、目录结构和操作方式以“当前主线”文档为准。已经批准但尚未全部实现的功能放在 `plans/`；已经被当前主线或新计划取代、但仍有追溯价值的资料放在 `archive/`。

> 当前应用版本为 V0.6.2。搜索、账号会话、任务所有权、多用户前端、Windows/Docker 升级、UI/UX 修正版和发布验收均已进入主线。

## 当前主线

- [产品需求与架构基线](产品需求与架构基线.md)
- [需求落实清单](需求落实清单.md)
- [V0.6.0 功能与验收](V0.6功能与验收.md)
- [V0.6.2 UI/UX Review](UI_UX_REVIEW_v0.6.2.md)
- [UI 问题与回归清单](UI_ISSUES.md)
- [账号权限与会话管理](账号权限与会话管理.md)
- [任务所有权与保留策略](任务所有权与保留策略.md)
- [QNAP Docker 部署指南](QNAP_Docker部署指南.md)
- [域名与反向代理配置](域名与反向代理配置.md)
- [备份、恢复与旧版本迁移](备份恢复与V0.4迁移.md)
- [发布、更新与回滚流程](发布与回滚流程.md)

## 当前目录边界

Windows / 源码运行目录：

```text
config/      配置和标签定义
userdata/    SQLite、任务、索引、日志、缓存和临时状态
downloads/   永久媒体文件
```

Docker 容器固定使用：

```text
/data/config
/data/userdata
/downloads
```

Docker 构建和 Compose 文件统一位于 `docker/`；根目录只保留三个 Windows 用户入口脚本。

## 开发计划状态

V0.6.0 PR 1–5 已全部完成。[V0.6.0 冻结方案](plans/V0.6.0_多用户搜索与会话方案.md)仅用于历史追溯。

V0.6.2 UI/UX 修正版已完成开发、自动化测试和发布。

后续功能需要建立新的版本计划，不再把已完成阶段作为待办。

## 历史资料

历史内容集中在 [`archive/`](archive/README.md)，历史发布报告位于 [`archive/releases/`](archive/releases/)。开发计划状态见 [`plans/`](plans/README.md)。
