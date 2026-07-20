# bili_workspace v0.6.2

`bili_workspace` 是一个可运行在 **Windows 本机** 和 **QNAP NAS / Docker** 上的私人 Bilibili 搜索、下载、任务管理与媒体库网站。

> 仅下载、保存和播放你有权使用的内容，并遵守适用法律、平台规则与版权要求。

## 主要能力

- 搜索区只请求 Bilibili 原始当前页结果；精准/模糊是浏览器内的当前页标题二级筛选，切换模式或修改筛选词不会联网；
- 首次只加载当前页，渲染完成后空闲时最多预加载下一页 1 页，不会后台抓取十页或全部页面；
- WBI 密钥按 Bilibili Cookie 指纹缓存 10 分钟，原始搜索页缓存 3 分钟；“刷新B站结果”只刷新当前页；
- 搜索响应直接包含标签、下载状态和删除状态；默认屏蔽已下载和已删除作品，关闭后可辨识并确认重新下载；
- 下载前预览可用清晰度，支持最低清晰度与目标档位，下载后核对实际分辨率、编码、帧率和文件大小；
- 任务中心显示真实进度、大小、速度、ETA、分 P 和日志，支持原 ID 重试、画质编辑及批量暂停、继续、取消、重试和删除；
- 作品库支持标签、无标签、分组/标签 chip、修改分组，以及按时间、观看、标题、时长、大小、分组和标签正逆序排序；
- 删除作品会移除作品库记录和媒体文件，同时在独立删除记录中保留搜索隐藏状态；显式重新下载成功后清除记录；
- 下载目标可选“保存到媒体库”或“导出到当前设备”；设备导出完整发送后立即删除服务器临时文件，中断时保留到 TTL 到期；
- 手机、平板和电脑浏览器在线播放，支持 `HEAD`、`Range`、`206`、`416`、拖动和续播；
- 默认优先播放原文件，不兼容时可手动生成 H.264/AAC MP4 兼容副本；
- 所有运行模式都要求网站账号登录；Windows 本机首次创建受限临时管理员并强制改密，Docker/NAS 使用一次性初始化令牌；
- 支持一个管理员和多个普通用户账号，每次登录使用独立 HttpOnly Token；每用户最多 10 个有效会话，第 11 次登录淘汰最久未连接设备；
- 改密轮换当前 Token/CSRF 并撤销其他会话，用户可管理自己的登录设备，管理员可创建、禁用和重置普通用户；
- 任务、日志、SSE 和设备导出按用户所有权隔离；普通用户只能导出到当前设备，最多 10 个活动任务，终态任务保留 7 天且最多 100 条；
- 管理员可查看全部用户任务并按用户、状态、目标、关键词和时间排序；不同用户可同时导出同一个 BV，互不占用临时产物；
- 普通用户网页只显示“下载”和“任务”，下载表单只允许导出到当前设备；顶部用户菜单可修改显示名、密码和登录设备；
- 管理员网页提供用户管理表格/手机卡片、会话撤销、临时密码重置，以及按用户筛选和分组的任务中心；
- V0.6.2 统一桌面端控件高度，将用户/分组 prompt 改为站内 Modal，并把 Bilibili 登录与网站账号/Token 设备管理拆成独立页签；
- 用户、分组等动态选择项较多时使用带搜索的两列列表，设置页将任务超时、轮询和编码策略折叠为高级设置；
- 提供 CSRF、可信 Host/代理、登录限速、安全 Cookie 和不记录明文凭据的审计日志；
- 网页 Bilibili 扫码登录，完整 Cookie 只保存在服务器端；
- Docker 镜像内包含 Python、固定依赖、Linux BBDown、FFmpeg 和 FFprobe。

## 持久化目录

本机和 Docker 都遵循同一职责边界：

```text
config/     配置、标签定义，以及容器内的 Bilibili 凭据
userdata/   SQLite、任务快照、下载索引、任务日志、缓存和临时文件
downloads/  只保存永久媒体文件
```

Docker 中分别映射为：

```text
/data/config
/data/userdata
/downloads
```

旧版位于 `config/` 的数据库，以及位于 `downloads/` 的索引和任务日志，会在目标不存在且文件安全可迁移时移动到 `userdata/`。不要把数据库、索引、日志或缓存重新放回媒体目录。

## 配置文件不会被 Git 覆盖

仓库只跟踪默认模板：

```text
.env.default
config/config.json.default
config/runtime.env.default
config/tags.json.default
docker/.env.default
```

实际运行文件不会提交：

```text
.env
config/config.json
config/runtime.env
config/tags.json
docker/.env
```

每次启动或更新都会执行：

1. 实际配置不存在时，从同名 `.default` 模板创建；
2. 实际配置已存在时，保留用户当前值和额外字段；
3. 新版模板增加字段时，只递归补入缺少的字段和默认值；
4. JSON 使用原子写入和备份；
5. 损坏的主配置不会被默认模板静默覆盖。

因此 `git pull`、重建容器或升级模板不会重置端口、目录映射、分组、任务数据库和账号设置。

## Windows 开箱即用

V0.5.6 将 Windows x64 的 Python 3.13.14、锁定 Python 依赖、BBDown 和 FFmpeg 集成到 Git 仓库。

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

`start.bat` 会自动校验仓库中的 `vendor/windows/*.pack`，安全解压到被 Git 忽略的 `.runtime/` 和 `BBDown_portable/`，同步配置并启动。它不访问 PyPI、不下载 GitHub Release，也不要求系统预装 Python、pip、BBDown 或 FFmpeg。

完整自检：

```bat
verify.bat
```

也可以双击 `update.bat` 完成拉取、配置同步和自检。根目录只保留 `start.bat`、`update.bat`、`verify.bat` 三个常用入口；可选和开发脚本统一收纳在 [`scripts/`](scripts/README.md)。实际配置、SQLite、任务、分组、下载媒体和 Bilibili 凭据均保持未跟踪，不会被 `git pull` 覆盖。

## IP、端口和手机访问

默认仅本机访问：

```text
127.0.0.1:3398
```

网站设置页可直接启用局域网访问；命令行备用入口为 `scripts\windows\configure-network.bat`。监听地址和端口支持任意合法值，其中手机访问电脑时通常设置：

```text
监听地址：0.0.0.0
端口：3398、3389 或其他未被占用的端口
```

然后访问：

```text
http://电脑局域网IP:端口/
```

所有模式均要求登录。Windows 全新安装会在回环地址创建强制改密的临时管理员；具体初始凭据以启动提示和账号文档为准。默认密码未修改前拒绝切换到非回环监听。Windows 防火墙需允许相应端口；若远程桌面占用 TCP 3389，请使用 3398、8080 或其他端口。

## QNAP / Docker

Docker 默认使用 GHCR 多架构镜像：

```text
ghcr.io/kachekakaka/bili_workspace:latest
```

支持 `linux/amd64` 和 `linux/arm64`。第一次部署：

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

默认 `BUILD_LOCAL=false`，直接拉取预构建镜像。无法访问 GHCR 或需要自行构建时设置：

```env
BUILD_LOCAL=true
```

固定持久化映射：

```text
/data/config    配置、标签定义和 Bilibili 凭据
/data/userdata  SQLite、任务、分组、会话、观看进度、删除记录、索引、日志、缓存和临时文件
/downloads      永久媒体文件；不保存数据库、索引、日志或缓存
```

完整步骤见 [QNAP Docker 部署指南](docs/QNAP_Docker部署指南.md)。

## 域名访问

推荐拓扑：

```text
https://bili.example.com:443
        ↓ QNAP HTTPS 反向代理
NAS 局域网地址:3398
        ↓
bili-workspace 容器
```

公网只开放 HTTPS 443，不建议同时暴露应用端口。详细设置见 [域名与反向代理配置](docs/域名与反向代理配置.md)。

## 数据和备份

Docker/QNAP 至少备份三个宿主机映射目录：

```text
CONFIG_DIR
USERDATA_DIR
MEDIA_DIR
```

其中 `USERDATA_DIR/cache` 与 `USERDATA_DIR/tmp` 可重建，可按备份策略排除；SQLite、任务状态、索引和日志仍位于 `USERDATA_DIR`，不能只备份配置和媒体。

Windows 建议备份：

```text
config/
userdata/
downloads/
BBDown_portable/BBDown.data（敏感，需加密保存）
```

复制正在运行的 SQLite 数据库前应先停止应用，或使用支持 SQLite 一致性快照的备份方式。schema 升级会先在 `userdata/backups/` 自动生成 SQLite 一致性备份并保留最近 3 份。

## 验证

Windows：

```text
verify.bat
```

Linux/macOS 源码环境：

```bash
python -m pip install -r requirements/dev.lock
sh scripts/dev/verify-source.sh
```

验证内容包括配置模板边界、Markdown 内部链接、敏感信息扫描、Python 编译、Ruff、完整 pytest、前端 JavaScript 语法，以及 Windows 上的 Portable Python、BBDown 和 FFmpeg 冒烟测试。CI 还会使用 Playwright Chromium 检查 1920×1080、1440×900、1024×768、768×1024 和 390×844 五个固定视口。

本地已有 Playwright 浏览器时可执行布局专项：

```bash
BILI_RUN_PLAYWRIGHT=1 python -m pytest -q tests/test_playwright_layout.py tests/test_v062_ui_playwright.py
```

## 仓库边界

Git 仓库不提交：

```text
实际配置和 .env
.venv
BBDown.data
SQLite 数据库
媒体文件、任务快照、索引、日志、缓存和临时文件
解压后的 .runtime、BBDown.exe 与 ffmpeg.exe
```

仓库提交的是校验后的 `vendor/windows/python-runtime.pack` 与 `media-runtime.pack`，而不是不可移植的 `.venv`。运行时在本机解压；Docker 使用 GHCR 多架构镜像。

更多文档：

- [文档索引](docs/README.md)
- [当前需求落实清单](docs/需求落实清单.md)
- [V0.6.0 功能与验收](docs/V0.6功能与验收.md)
- [V0.6.2 UI/UX Review](docs/UI_UX_REVIEW_v0.6.2.md)
- [UI 问题与回归清单](docs/UI_ISSUES.md)
- [账号权限与会话管理](docs/账号权限与会话管理.md)
- [任务所有权与保留策略](docs/任务所有权与保留策略.md)
- [产品需求与架构基线](docs/产品需求与架构基线.md)
- [QNAP Docker 部署指南](docs/QNAP_Docker部署指南.md)
- [配置目录说明](config/README.md)
- [运行数据目录说明](userdata/README.md)
- [源文件与恢复清单](docs/源文件与恢复清单.md)

## 已知边界

- BBDown 上游已停止维护，Bilibili 接口或扫码协议变化后可能需要替换下载适配层；
- V0.6.2 已完成搜索、账号会话、任务所有权、多用户前端、UI/UX 修正版和发布验收；不提供开放注册或匿名公开分享；
- 不自动为所有作品生成 HLS/多码率版本，兼容副本按需生成。
