# bili_workspace v0.5.4

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

源码仓库本身不把第三方 EXE、离线 wheelhouse 或 `.venv` 写入 Git 历史。`setup.bat` 会优先复用已有文件；缺失时从 `v0.5.4` GitHub Release 下载固定的 Windows 运行包，校验整个 ZIP 和内部逐文件 SHA-256，然后安装到：

```text
BBDown_portable/BBDown.exe
BBDown_portable/ffmpeg/bin/ffmpeg.exe
wheelhouse/*.whl
```

网络受限时，也可以把下面的文件放在仓库根目录，再运行 `setup.bat`：

```text
bili_workspace_v0.5.4_windows_runtime.zip
```

完整 Windows 发布包已经包含这些文件，因此可以离线创建 `.venv`。运行包和完整包作为 GitHub Release 资产保存，而不是进入普通源码提交。

只检查源码、不安装 BBDown/FFmpeg 时，可以直接运行：

```bat
verify-source.bat
```

首次运行时它会创建 `.venv` 并安装 Python 依赖，但会显式跳过 Windows 媒体运行包下载；需要真实下载、混流和扫码登录时，再运行 `setup.bat` 补齐运行包。

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

非回环监听会自动切换到服务器模式，并强制创建管理员账号。Windows 防火墙需要允许所选 TCP 端口的“专用网络”访问。

`3389` 可以配置，但 Windows 远程桌面常使用该端口；如有冲突，请使用 `3398`、`8080` 或其他空闲端口。

## QNAP / Docker

推荐目录映射：

```text
/data/config  配置、SQLite、管理员、任务、分组、会话、Bilibili 登录凭据
/data/media   永久媒体文件
/data/cache   封面和兼容播放副本
/data/tmp     下载、混流、导出和转码临时文件
```

QNAP `.env` 示例：

```env
CONFIG_DIR=/share/Container/bili-workspace/config
MEDIA_DIR=/share/Multimedia/Bilibili
CACHE_DIR=/share/Container/bili-workspace/cache
TEMP_DIR=/share/Container/bili-workspace/tmp

HOST_BIND_IP=0.0.0.0
HTTP_PORT=3398
PUID=1000
PGID=100
TZ=Asia/Shanghai

PUBLIC_BASE_URL=https://bili.example.com
TRUSTED_HOSTS=bili.example.com
TRUSTED_PROXY_IPS=QNAP反向代理实际来源IP
COOKIE_SECURE=true
ENABLE_HSTS=false
```

启动：

```bash
cp docker/.env.default docker/.env
# 编辑 docker/.env
./docker/verify-config.sh
./docker/build-and-start.sh
```

容器使用非 root 用户、只读根文件系统、`cap_drop: ALL`、`no-new-privileges` 和健康检查；无需 privileged，也不挂载 Docker socket。

公网部署建议：

```text
手机/浏览器 → HTTPS 443 → QNAP 反向代理 → 容器 HTTP_PORT
```

只公开 443，不要将应用管理端口直接裸露到公网。确认 HTTPS、Cookie 和登录均正常后再启用 HSTS。

## 数据持久化

SQLite 和用户数据位于配置目录。Docker 中为：

```text
/data/config/bili_workspace.db
```

Windows 默认位于项目运行数据目录。数据库记录管理员、服务端会话、逻辑分组、媒体文件、观看进度、任务快照、设备导出、兼容转码和审计日志。

容器或 NAS 重启后：

- 已完成任务保持不变；
- 排队任务恢复排队；
- 运行中的任务标记为中断，可重新提交；
- 分组、作品库、账号和播放进度不会丢失；
- 设备导出临时文件继续按 TTL 管理。

备份重点：

```text
CONFIG_DIR
MEDIA_DIR
```

`CACHE_DIR` 可以按需要备份，`TEMP_DIR` 不需要备份。

## 设备导出

下载目标选择“导出到当前设备”时：

1. NAS 在 `/data/tmp` 中完成下载和混流；
2. 单文件以附件流式返回，多文件自动打包 ZIP；
3. 响应体全部发送后立即删除对应临时目录；
4. 客户端中断时保留文件，允许重试；
5. 超过 TTL 的残留由清理任务删除。

服务器只能确认响应字节已全部发出，不能确认浏览器最终写入磁盘成功。唯一重要内容建议先保存到媒体库，再从作品库下载到设备。

## 浏览器播放

媒体接口支持：

```text
HEAD
Range
206 Partial Content
416 Range Not Satisfiable
ETag
Last-Modified
Accept-Ranges
```

默认优先播放原始文件。浏览器不支持 HEVC、AV1 或音频编码时，可以手动创建：

```text
H.264 + AAC + MP4
```

兼容副本保存在缓存目录，不覆盖原文件，默认转码并发为 1。

## Bilibili 网页扫码登录

账号页可以创建二维码，并显示：

```text
等待扫码
已扫码，等待确认
登录成功
二维码过期
```

完整 Cookie 只由后端写入配置秘密目录，不通过浏览器 API 返回，不进入日志或 Git。退出登录会删除对应凭据。

BBDown v1.6.3 已停止维护；未来若 Bilibili 登录或解析接口变化，需要更换下载适配层。

## 开发与验证

支持 Python：

```text
3.11
3.12
3.13
```

安装开发依赖：

```bash
python -m pip install -r requirements.lock
```

运行：

```bash
python -m compileall -q app tests tools docker
python -m ruff check --no-cache app tests tools docker
python -m pytest -q -p no:cacheprovider
./verify-source.sh
```

验证项目包括配置模板边界、敏感信息扫描、Python 编译、Ruff、完整 pytest、前端 JavaScript 语法，以及工具存在时的 BBDown/FFmpeg 真实启动冒烟测试。

## 仓库边界

不提交：

```text
真实 .env 和 JSON 配置
BBDown.data
管理员初始化令牌
SQLite 数据库
任务日志
下载视频
导出和转码临时文件
封面缓存
.venv
Windows BBDown.exe、ffmpeg.exe 与 wheelhouse
```

不提交 `.venv` 是因为它包含创建机器的绝对路径、Python ABI 和平台相关启动器，跨目录、跨 Python 小版本或跨 Windows/Linux 不可靠。依赖由锁定文件、Release 运行包和 `setup.bat` 重建；Docker 运行环境由镜像重建。

更多说明见 [源码仓库与发布包](docs/源码仓库与发布包.md)。

完整需求映射见 [V0.5.4 需求落实清单](docs/需求落实清单.md)，长期开发依据见 [产品需求与架构基线](docs/产品需求与架构基线.md)，发布边界见 [V0.5.4 发布与验证说明](docs/V0.5.4_发布与验证说明.md)，配置目录说明见 [config/README.md](config/README.md)，可恢复源文件与发布资产见 [源文件与恢复清单](docs/源文件与恢复清单.md)。
