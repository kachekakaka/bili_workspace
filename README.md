# bili_workspace v0.5.3

`bili_workspace` 是一个可运行在 **Windows 本机** 和 **QNAP NAS / Docker** 上的私人 Bilibili 下载与媒体库网站。

> 仅下载、保存和播放你有权使用的内容，并遵守适用法律、平台规则与版权要求。

## 主要能力

- 搜索作品、查看标题/BV/封面，并在下载前预览可用清晰度；
- 设置最低清晰度和目标档位，下载完成后显示实际分辨率、编码、帧率和文件大小；
- 下载时选择已有分组或立即新建分组，分组页支持浏览、重命名、合并和删除空分组；
- 下载目标可选“保存到媒体库”或“导出到当前设备”；设备导出完整发送后立即删除服务器临时文件，中断时保留到 TTL 到期；
- 手机、平板和电脑浏览器在线播放，支持 `HEAD`、`Range`、`206`、`416`、拖动和续播；
- 默认优先播放原文件，不兼容时可手动生成 H.264/AAC MP4 兼容副本；
- SQLite 持久化管理员、会话、任务、逻辑分组、作品库和观看进度；
- 服务器模式强制管理员认证，并提供 CSRF、可信 Host/代理、登录限速、安全 Cookie 和审计日志；
- 网页 Bilibili 扫码登录，完整 Cookie 只保存在服务器端；
- Docker 镜像内构建 Python、固定依赖、Linux BBDown、FFmpeg 和 FFprobe。

## 配置文件不会被 Git 覆盖

仓库只跟踪默认模板：

```text
.env.default
config/config.json.default
config/runtime.env.default
docker/.env.default
```

实际运行文件不会提交：

```text
.env
config/config.json
config/runtime.env
docker/.env
```

每次安装、启动或更新都会执行以下规则：

1. 实际配置不存在时，从同名 `.default` 模板创建；
2. 实际配置已存在时，保留用户当前值和额外字段；
3. 新版模板增加字段时，只递归补入缺少的字段和默认值；
4. JSON 使用原子写入和备份；
5. 损坏的主配置不会被默认模板静默覆盖，存在备份时由配置存储恢复。

因此 `git pull`、重新构建容器或升级默认模板不会重置端口、目录映射、分组、任务数据库和账号设置。

## Windows 使用

### 从完整 Windows 包更新

最方便的方式是保留完整包目录中的：

```text
BBDown_portable/BBDown.exe
BBDown_portable/ffmpeg/bin/ffmpeg.exe
```

这两个文件和 `BBDown.data` 都被 `.gitignore` 排除，拉取源码更新时不会被删除或覆盖。

### 从全新 Git 克隆运行

```bat
git clone https://github.com/kachekakaka/bili_workspace.git
cd bili_workspace
setup.bat
verify.bat
start.bat
```

源码仓库不携带 Windows 第三方二进制。没有 BBDown/FFmpeg 时，网站和媒体库可以启动，但真实搜索、扫码登录、下载、混流和兼容转码不可用。请将已验证的工具放到：

```text
BBDown_portable/BBDown.exe
BBDown_portable/ffmpeg/bin/ffmpeg.exe
```

随后重新运行 `verify.bat`。

### 后续更新

双击：

```text
update.bat
```

它会检查受 Git 管理的本地修改，执行 `git pull --ff-only origin main`，同步依赖和配置，再运行完整自检。

## IP、端口和手机访问

默认只允许本机访问：

```text
127.0.0.1:3398
```

双击 `configure_network.bat` 可以设置任意合法监听地址和 `1–65535` 端口。

手机访问电脑时通常设置：

```text
监听地址：0.0.0.0
端口：3398、3389 或其他未被占用的端口
```

然后手机在同一局域网访问：

```text
http://电脑局域网IP:端口/
```

例如：

```text
http://192.168.1.50:3398/
```

非回环监听会自动切换为服务器模式并强制网站管理员认证。Windows 防火墙还需允许该端口进入；若电脑启用了远程桌面，TCP 3389 很可能已被占用，建议使用 3398、8080 或其他端口。

也可以编辑 `.env`：

```env
BILI_APP_MODE=auto
BILI_HOST=0.0.0.0
BILI_PORT=3398
```

环境变量优先于 JSON 配置。

## QNAP / Docker

完整步骤见 [QNAP Docker 部署指南](docs/QNAP_Docker部署指南.md)。基本流程：

```bash
git clone https://github.com/kachekakaka/bili_workspace.git
cd bili_workspace
chmod +x docker/*.sh verify-source.sh
./docker/ensure-env.sh
vi docker/.env
./docker/verify-config.sh
./docker/build-and-start.sh
```

`docker/.env` 中配置 QNAP 宿主机目录：

```env
CONFIG_DIR=/share/Container/bili-workspace/config
MEDIA_DIR=/share/Multimedia/Bilibili
CACHE_DIR=/share/Container/bili-workspace/cache
TEMP_DIR=/share/Container/bili-workspace/tmp
BIND_IP=0.0.0.0
HTTP_PORT=3398
```

容器内固定映射：

```text
/data/config  配置、SQLite、任务、分组、管理员、会话和 Bilibili 凭据
/data/media   永久媒体文件与兼容旧版的下载索引
/data/cache   封面缓存和手动生成的兼容播放副本
/data/tmp     下载、混流、转码和设备导出的临时文件
```

更新代码和重建容器不会删除这些宿主机映射目录。

## 域名访问

推荐拓扑：

```text
https://bili.example.com:443
        ↓ QNAP HTTPS 反向代理
NAS 局域网地址:3398
        ↓
bili-workspace 容器
```

公网只开放 HTTPS 443，不建议同时把应用端口直接暴露到互联网。域名、可信 Host、可信代理、安全 Cookie 和 HSTS 的设置见 [域名与反向代理配置](docs/域名与反向代理配置.md)。

## 数据和备份

Docker 必须备份：

```text
CONFIG_DIR
MEDIA_DIR
```

Windows 建议备份：

```text
config/
downloads/
BBDown_portable/BBDown.data（敏感，需加密保存）
```

`cache` 可重建，`tmp` 无需备份。详见 [备份恢复与 V0.4 迁移](docs/备份恢复与V0.4迁移.md)。

## 验证

Windows：

```text
verify.bat
```

Linux/macOS 源码环境：

```bash
python -m pip install -r requirements.lock
./verify-source.sh
```

验证项目包括配置模板边界、敏感信息扫描、Python 编译、Ruff、完整 pytest、前端 JavaScript 语法，以及完整 Windows 包中的 BBDown/FFmpeg 冒烟测试。

## 仓库边界

Git 仓库不提交：

```text
实际配置和 .env
.venv
BBDown.data
SQLite 数据库
媒体文件、日志、缓存和临时文件
Windows BBDown.exe、ffmpeg.exe 与 wheelhouse
```

不提交 `.venv` 是因为它包含创建机器的绝对路径、Python ABI 和平台相关启动器，跨目录、跨 Python 小版本或跨 Windows/Linux 不可靠。依赖由锁定文件和 `setup.bat` 重建；Docker 运行环境由镜像重建。

更多说明见 [源码仓库与发布包](docs/源码仓库与发布包.md)。

完整需求映射见 [V0.5.3 需求落实清单](docs/需求落实清单.md)，长期开发依据见 [产品需求与架构基线](docs/产品需求与架构基线.md)，发布边界见 [V0.5.3 发布与验证说明](docs/V0.5.3_发布与验证说明.md)，配置目录说明见 [config/README.md](config/README.md)。

## 项目目录

```text
app/                     FastAPI 后端、队列、SQLite、认证和媒体流
web/                     响应式网页
config/*.default         应用和运行时配置模板
BBDown_portable/         Windows 工具放置位置和第三方许可证
Dockerfile               Docker 镜像构建
compose.yaml             QNAP/NAS Compose 配置
docker/                  配置同步、启动、入口和健康检查
docs/                    部署、迁移、安全、备份和验收文档
tests/                   回归与专项测试
tools/                   配置同步和发布/源码校验工具
```

## 已知边界

- BBDown 上游已停止维护，Bilibili 接口或扫码协议变化后可能需要替换下载适配层；
- 当前是单管理员私人媒体库，不提供开放注册或匿名公开分享；
- 不自动为所有作品生成 HLS/多码率版本，兼容副本按需生成；
- Docker 首次构建需要访问基础镜像、Python 软件源、Debian 软件源和固定 BBDown 发布文件。
