# QNAP Docker 部署指南（当前主线）

## 1. 前提

需要：

- QNAP Container Station；
- 可以在部署目录运行 Docker Compose 的终端；
- NAS 可拉取 `ghcr.io/kachekakaka/bili_workspace:latest`，或具备本地构建条件；
- 三个可写的宿主机目录；
- 运行容器账号的 PUID/PGID。

镜像支持 `linux/amd64` 和 `linux/arm64`。默认拉取 GHCR 预构建镜像；仅在无法拉取或需要自行构建时启用本地构建。

## 2. 创建持久化目录

示例：

```text
/share/Container/bili-workspace/config
/share/Container/bili-workspace/userdata
/share/Multimedia/Bilibili
```

用途：

```text
config    配置、标签定义、管理员初始化信息和 Bilibili 凭据
userdata  SQLite、任务快照、删除历史、下载索引、任务日志、缓存和临时状态
media     永久媒体文件
```

容器内部固定映射：

```text
/data/config
/data/userdata
/downloads
```

完整恢复至少需要备份 `config`、`userdata` 和媒体目录。`userdata/cache` 与 `userdata/tmp` 可按需排除，但数据库、索引和删除历史必须保留。

## 3. 确认权限

通过 SSH 查看运行账号：

```bash
id 用户名
```

把 uid/gid 填入 `docker/.env`。该账号必须对三个目录有读写权限。容器不会使用 privileged，也不会自动修改宿主机权限。

## 4. 克隆与生成配置

```bash
cd /share/Container/bili-workspace
git clone https://github.com/kachekakaka/bili_workspace.git app
cd app
chmod +x docker/*.sh verify-source.sh
cp docker/.env.default docker/.env
vi docker/.env
```

`docker/.env` 不进入 Git。新版模板增加字段时，启动脚本只补充缺失变量，不覆盖现有值。

至少检查：

```env
CONFIG_DIR=/share/Container/bili-workspace/config
USERDATA_DIR=/share/Container/bili-workspace/userdata
MEDIA_DIR=/share/Multimedia/Bilibili

BILI_IMAGE=ghcr.io/kachekakaka/bili_workspace:latest
BUILD_LOCAL=false

PUID=1000
PGID=100
TZ=Asia/Shanghai
BIND_IP=0.0.0.0
HTTP_PORT=3398
PUBLIC_BASE_URL=
TRUSTED_HOSTS=127.0.0.1,localhost
TRUSTED_PROXY_IPS=127.0.0.1
COOKIE_SECURE=false
ENABLE_HSTS=false
BOOTSTRAP_TOKEN=
EXPORT_TTL_SEC=86400
MIN_FREE_GIB=2
DOWNLOAD_CONCURRENCY=1
TRANSCODE_THREADS=0
```

`BIND_IP` 可使用 `0.0.0.0`、NAS 某个局域网 IP 或 `127.0.0.1`；`HTTP_PORT` 可使用 1–65535 中未被占用的端口。

## 5. 校验、构建和启动

```bash
./docker/verify-config.sh
./docker/build-and-start.sh
```

脚本会根据 `BUILD_LOCAL`：

- `false`：拉取 `BILI_IMAGE`；
- `true`：执行本地 `docker compose build --pull`。

常用命令：

```bash
docker compose --env-file docker/.env config
docker compose --env-file docker/.env up -d
docker compose --env-file docker/.env ps
docker compose --env-file docker/.env logs -f --tail=100 app
```

健康检查：

```text
http://NAS局域网IP:HTTP_PORT/healthz
```

## 6. 首次管理员初始化

服务器/Docker 模式始终要求管理员登录。首次启动若未在 `docker/.env` 设置 `BOOTSTRAP_TOKEN`，一次性令牌会写入：

```text
CONFIG_DIR/bootstrap-token.txt
```

打开网站，输入管理员用户名、强密码和一次性令牌。成功后令牌文件自动删除。

## 7. 局域网和手机访问

局域网直接访问：

```text
http://NAS局域网IP:HTTP_PORT/
```

确认：

- `BIND_IP` 不是 `127.0.0.1`；
- QNAP 防火墙允许局域网访问 `HTTP_PORT`；
- 手机和 NAS 路由可达；
- 手机代理、电脑代理或旁路由没有代理局域网地址；
- 必要时把 NAS IP 和局域网网段加入直连/绕过代理列表；
- 管理员初始化已经完成。

应用设置页会展示可用访问地址。多网卡时可逐一尝试页面列出的局域网 IP。

## 8. 域名访问

推荐由 QNAP HTTPS 反向代理把 443 转发到 NAS 局域网地址和 `HTTP_PORT`。此时设置：

```env
PUBLIC_BASE_URL=https://bili.example.com
TRUSTED_HOSTS=bili.example.com
TRUSTED_PROXY_IPS=应用实际看到的反向代理来源IP
COOKIE_SECURE=true
ENABLE_HSTS=false
```

先确认 HTTPS、登录和 Cookie 正常，再考虑启用 HSTS。禁止把 `TRUSTED_HOSTS` 或 `TRUSTED_PROXY_IPS` 设为 `*`。

## 9. Bilibili 扫码登录

进入“账号”页面，点击网页扫码登录并在 Bilibili App 中确认。凭据保存在：

```text
CONFIG_DIR/bbdown/BBDown.data
```

完整 Cookie 不返回浏览器。不要公开 `CONFIG_DIR`、数据库、备份或 `docker/.env`。

## 10. 当前数据位置

```text
/data/config
  runtime.env
  config.json
  tags.json
  bbdown/BBDown.data

/data/userdata
  bili_workspace.db
  bili_workspace.db-wal / -shm
  indexes/
  task_logs/
  cache/
  tmp/

/downloads
  实际媒体文件
```

SQLite 中包含作品库、标签关系、任务快照、观看记录和 `deleted_media` 删除历史。删除历史不会出现在作品库，但搜索可标记“已删除”。

## 11. 更新

```bash
cd /share/Container/bili-workspace/app
git pull --ff-only origin main
./docker/build-and-start.sh
```

代码更新会拉取或重新构建镜像，但不会删除三个宿主机映射目录。配置模板的新字段会在启动时补入实际配置。

## 12. 停止与恢复

停止但保留数据：

```bash
docker compose --env-file docker/.env down
```

恢复步骤：

1. 停止容器；
2. 恢复 `CONFIG_DIR`、`USERDATA_DIR` 和 `MEDIA_DIR`；
3. 确认 PUID/PGID 对三个目录可读写；
4. 运行 `./docker/build-and-start.sh`；
5. 检查管理员、作品数量、分组、标签、删除历史、任务和播放记录。

## 13. 常见问题

### 容器反复重启

检查：

- 三个目录是否存在且对 PUID/PGID 可写；
- 端口是否被占用；
- NAS 是否能拉取 GHCR 镜像，或本地构建所需网络是否可用；
- 域名是否在 `TRUSTED_HOSTS`；
- 反向代理来源 IP 是否正确；
- `CONFIG_DIR/bbdown` 中的程序是否可执行。

### 手机无法访问

检查 `BIND_IP`、QNAP 防火墙、手机代理/旁路由和访问地址。不要使用 `localhost` 或 `127.0.0.1` 从手机访问。

### 浏览器不能播放

先尝试原文件。设备不支持 HEVC/AV1 或音频编码时，在作品详情中手动生成兼容播放版。软件转码会占用 NAS CPU。
