# bili_workspace v0.7.0

`bili_workspace` 是一个可运行在 **Windows 本机** 和 **QNAP NAS / Docker** 上的私人 Bilibili 搜索、下载、任务管理与媒体库网站。

> 仅下载、保存和播放你有权使用的内容，并遵守适用法律、平台规则与版权要求。

## V0.7.0 重点

V0.7.0 不扩大业务范围，完成前端内部结构整理：

- 所有页面使用浏览器原生 `.mjs` ES Modules 和静态 import；
- 每个路由只有一个正式 renderer，统一 `mount(root, context)` / 幂等 `dispose()` 生命周期；
- Router 在切页时取消旧请求、旧订阅和旧事件，只有当前 generation 可以提交结果；
- API、Session、Context、Modal、Toast、Confirm 和 TaskStream 各只有一份实现；
- Dashboard 与 Tasks 共享唯一 `/api/events` EventSource；
- Search、Library、Tasks、账号、设置、用户和分组均已脱离 DOM overlay、MutationObserver 和事件抢占；
- 删除旧 `app.js`、全部 `enhancements-*`、Legacy Bridge、版本脚本和版本专用 CSS 覆盖；
- 最终入口只保留第三方 `qrcode.min.js`、`app/main.mjs` 和 tokens/base/components/pages 四层 CSS；
- 版本不一致时页面提供明确的重启服务与强制刷新提示；
- 不修改下载算法、API、权限、标签模型、持久化目录或 SQLite schema v4。

## 主要能力

- 搜索只请求 Bilibili 当前页；精准/模糊仅在浏览器内筛选当前页标题，不增加网络请求；
- 当前页渲染成功后最多预加载下一页 1 页，不抓取第三页、十页或全部页面；
- 搜索支持已下载/已删除识别、跨页选择、标签、画质预览和批量下载；
- 下载支持媒体库和当前设备导出、最低清晰度、指定档位和实际码流核验；
- 任务中心显示进度、大小、速度、ETA、分 P 和日志，支持单项与批量暂停、继续、取消、重试和删除；
- 作品库支持服务端分页、分组/标签/无标签筛选、多字段升降序、播放器、Range、续播、批量标签/下载/删除和修改分组；
- 一个管理员和多个普通用户，每用户最多 10 个 HttpOnly 登录 Token；
- 普通用户只可使用“下载”和“任务”，且只能导出到当前设备；任务、日志、SSE 和导出按所有者隔离；
- Bilibili 扫码凭据只保存在服务器端；
- Windows、Docker/QNAP 使用同一配置、数据库和媒体职责边界。

## 持久化目录

Windows / 源码运行：

```text
config/     配置、标签定义，以及本机/容器的 Bilibili 凭据
userdata/   SQLite、任务、索引、日志、缓存和临时状态
downloads/  永久媒体文件
```

Docker 固定映射：

```text
/data/config
/data/userdata
/downloads
```

仓库只跟踪 `.default` 模板；实际 `.env`、配置、SQLite、任务、媒体和凭据均被 Git 忽略。升级只补充缺少的默认字段，不覆盖已有用户值。运行数据的详细职责与恢复边界见 [`userdata/README.md`](userdata/README.md)。

## Windows 开箱即用

全新安装：

```bat
git clone https://github.com/kachekakaka/bili_workspace.git
cd bili_workspace
start.bat
```

已有目录更新：

```bat
git pull --ff-only origin main
start.bat
```

`start.bat` 使用仓库内经过校验的 Windows Portable Python、固定依赖、BBDown 和 FFmpeg 运行包，不依赖系统 Python、PyPI 或临时 Release 下载。

完整自检：

```bat
verify.bat
```

`verify.bat` 会验证源码边界、Python compileall、Ruff、完整 pytest、所有 `.js/.mjs` 语法、依赖无关 Node 单元测试，以及内置 Python、BBDown、FFmpeg 冒烟。

## IP、端口和手机访问

默认仅本机监听：

```text
127.0.0.1:3398
```

可在设置页或 `scripts\windows\configure-network.bat` 配置 `0.0.0.0`、指定局域网 IP、主机名和 1–65535 端口。默认管理员密码未修改前拒绝切换到非回环监听。

## QNAP / Docker

默认镜像：

```text
ghcr.io/kachekakaka/bili_workspace:latest
ghcr.io/kachekakaka/bili_workspace:v0.7.0
```

支持 `linux/amd64` 和 `linux/arm64`。首次部署：

```bash
git clone https://github.com/kachekakaka/bili_workspace.git
cd bili_workspace
chmod +x docker/*.sh
cp docker/.env.default docker/.env
# 修改 QNAP 三个宿主机目录、PUID/PGID、端口和域名设置
./docker/build-and-start.sh
```

以后更新：

```bash
git pull --ff-only origin main
./docker/build-and-start.sh
```

默认拉取 GHCR 镜像；无法访问 GHCR 时可在 `docker/.env` 设置 `BUILD_LOCAL=true` 本地构建。完整步骤见 [QNAP Docker 部署指南](docs/QNAP_Docker部署指南.md)。

## 备份与升级

至少备份：

```text
Windows：config/、userdata/、downloads/、BBDown_portable/BBDown.data
Docker：CONFIG_DIR、USERDATA_DIR、MEDIA_DIR
```

复制运行中的 SQLite 前应停止服务或使用一致性快照。schema 升级会在 `userdata/backups/` 创建 SQLite 备份并只保留最近 3 份。

V0.7.0 **不升级数据库 schema**，继续使用 v4。由 v0.6.2 升级到 v0.7.0 是纯代码和前端结构升级，可保留原配置、userdata 和媒体目录直接启动。回滚前仍应停止服务并备份现场。

## 验证

Linux/macOS 源码环境：

```bash
python -m pip install -r requirements/dev.lock
sh scripts/dev/verify-source.sh
```

CI 发布门禁包括：

- Python 3.11、3.12、3.13；
- compileall、Ruff、完整 pytest；
- 全部 `.js/.mjs` 语法和 Node 单元测试；
- Playwright 1920×1080、1440×900、1024×768、768×1024、390×844；
- Windows `verify.bat` 干净检出与原地升级；
- Docker build、持久化/迁移测试和镜像内 `0.7.0` 冒烟。

## 文档

- [文档索引](docs/README.md)
- [V0.7.0 功能与验收](docs/V0.7功能与验收.md)
- [V0.7.0 Release notes](docs/releases/V0.7.0.md)
- [当前需求落实清单](docs/需求落实清单.md)
- [账号权限与会话管理](docs/账号权限与会话管理.md)
- [任务所有权与保留策略](docs/任务所有权与保留策略.md)
- [发布、更新与回滚流程](docs/发布与回滚流程.md)
- [QNAP Docker 部署指南](docs/QNAP_Docker部署指南.md)
- [运行数据目录说明](userdata/README.md)
- [源文件与恢复清单](docs/源文件与恢复清单.md)

## 已知边界

- BBDown 上游已停止维护，Bilibili 接口或扫码协议变化后可能需要替换下载适配层；
- 不提供开放注册、多管理员、匿名公开分享或每用户独立 Bilibili 凭据；
- 不自动为所有作品生成 HLS/多码率版本，兼容副本按需生成；
- V0.7.0 是前端结构整理版本，不改变既有业务、API、权限或数据库模型。
