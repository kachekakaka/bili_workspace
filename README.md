# bili_workspace v0.5.6

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

也可以双击 `update.bat` 完成拉取、配置同步和自检。实际配置、SQLite、任务、分组、下载媒体和 Bilibili 凭据均保持未跟踪，不会被 `git pull` 覆盖。

## IP、端口和手机访问

默认仅本机访问：

```text
127.0.0.1:3398
```

双击 `configure_network.bat` 可设置任意合法监听地址和 `1–65535` 端口。手机访问电脑时通常设置：

```text
监听地址：0.0.0.0
端口：3398、3389 或其他未被占用的端口
```

然后访问：

```text
http://电脑局域网IP:端口/
```

非回环监听会自动切换为服务器模式并强制管理员认证。Windows 防火墙需允许相应端口；若远程桌面占用 TCP 3389，请使用 3398、8080 或其他端口。

## QNAP / Docker

Docker 默认使用 GHCR 多架构镜像：

```text
ghcr.io/kachekakaka/bili_workspace:latest
```

支持 `linux/amd64` 和 `linux/arm64`。第一次部署：

```bash
git clone https://github.com/kachekakaka/bili_workspace.git
cd bili_workspace
chmod +x docker/*.sh verify-source.sh
cp docker/.env.default docker/.env
# 修改 QNAP 四个宿主机目录、PUID/PGID、端口和域名设置
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
/data/config  配置、SQLite、任务、分组、管理员、会话和 Bilibili 凭据
/data/media   永久媒体文件与下载索引
/data/cache   封面缓存和兼容播放副本
/data/tmp     下载、混流、转码和设备导出临时文件
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

`cache` 可重建，`tmp` 无需备份。

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

验证内容包括配置模板边界、敏感信息扫描、Python 编译、Ruff、完整 pytest、前端 JavaScript 语法，以及 Windows 上的 Portable Python、BBDown 和 FFmpeg 冒烟测试。

## 仓库边界

Git 仓库不提交：

```text
实际配置和 .env
.venv
BBDown.data
SQLite 数据库
媒体文件、日志、缓存和临时文件
解压后的 .runtime、BBDown.exe、ffmpeg.exe 与 wheelhouse
```

仓库提交的是校验后的 `vendor/windows/python-runtime.pack` 与 `media-runtime.pack`，而不是不可移植的 `.venv`。运行时在本机解压；Docker 使用 GHCR 多架构镜像。

更多文档：

- [V0.5.6 需求落实清单](docs/需求落实清单.md)
- [产品需求与架构基线](docs/产品需求与架构基线.md)
- [V0.5.6 发布与验证说明](docs/V0.5.6_发布与验证说明.md)
- [配置目录说明](config/README.md)
- [源文件与恢复清单](docs/源文件与恢复清单.md)

## 已知边界

- BBDown 上游已停止维护，Bilibili 接口或扫码协议变化后可能需要替换下载适配层；
- 当前是单管理员私人媒体库，不提供开放注册或匿名公开分享；
- 不自动为所有作品生成 HLS/多码率版本，兼容副本按需生成。
