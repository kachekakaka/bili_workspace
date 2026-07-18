# QNAP Docker 部署指南（V0.5.3）

## 1. 前提

需要：

- QNAP Container Station；
- 可以在部署目录运行 Docker Compose 的终端；
- NAS 可访问基础镜像、Python/Debian 软件源和固定 BBDown 发布文件；
- 四个可写的宿主机目录；
- 运行容器账号的 PUID/PGID。

Dockerfile 支持 `linux/amd64` 和 `linux/arm64`，构建时按目标架构选择 BBDown Linux 资产。

## 2. 创建持久化目录

示例：

```text
/share/Container/bili-workspace/config
/share/Container/bili-workspace/cache
/share/Container/bili-workspace/tmp
/share/Multimedia/Bilibili
```

用途：

```text
config  配置、SQLite、管理员、任务、分组、播放进度和 Bilibili 会话
media   永久视频和下载索引
cache   封面和兼容播放副本
tmp     下载、混流、转码和一次性设备导出临时文件
```

`config` 和 `media` 必须纳入备份策略；`tmp` 不需要备份。

## 3. 确认权限

通过 SSH 查看运行账号：

```bash
id 用户名
```

把 uid/gid 填入 `docker/.env`。该账号必须对四个目录有读写权限。容器不会使用 privileged，也不会自动修改宿主机权限。

## 4. 克隆与生成配置

```bash
cd /share/Container/bili-workspace
git clone https://github.com/kachekakaka/bili_workspace.git app
cd app
chmod +x docker/*.sh verify-source.sh
./docker/ensure-env.sh
vi docker/.env
```

`docker/.env` 不进入 Git。新版 `docker/.env.default` 增加字段时，`ensure-env.sh` 只追加缺失字段，不覆盖现有值。

至少检查：

```env
CONFIG_DIR=/share/Container/bili-workspace/config
MEDIA_DIR=/share/Multimedia/Bilibili
CACHE_DIR=/share/Container/bili-workspace/cache
TEMP_DIR=/share/Container/bili-workspace/tmp
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
```

`BIND_IP` 可使用 `0.0.0.0`、NAS 某个局域网 IP 或 `127.0.0.1`；`HTTP_PORT` 可使用 1–65535 中未被占用的端口，包括 3389。

## 5. 校验、构建和启动

```bash
./docker/verify-config.sh
./docker/build-and-start.sh
```

脚本等价于使用：

```bash
docker compose --env-file docker/.env config
docker compose --env-file docker/.env build --pull
docker compose --env-file docker/.env up -d
docker compose --env-file docker/.env ps
```

查看日志：

```bash
docker compose --env-file docker/.env logs -f --tail=100 app
```

## 6. 首次管理员初始化

服务器/Docker 模式始终要求管理员登录。首次启动若未在 `docker/.env` 设置 `BOOTSTRAP_TOKEN`，一次性令牌会写入：

```text
CONFIG_DIR/bootstrap-token.txt
```

打开网站，输入管理员用户名、强密码和一次性令牌。成功后令牌文件自动删除。

## 7. 局域网和域名访问

局域网直接访问：

```text
http://NAS局域网IP:HTTP_PORT/
```

域名访问推荐由 QNAP HTTPS 反向代理把 443 转发到 NAS 局域网地址和 `HTTP_PORT`。此时设置：

```env
PUBLIC_BASE_URL=https://bili.example.com
TRUSTED_HOSTS=bili.example.com
TRUSTED_PROXY_IPS=应用实际看到的反向代理来源IP
COOKIE_SECURE=true
ENABLE_HSTS=false
```

先确认 HTTPS、登录和 Cookie 正常，再考虑启用 HSTS。禁止把 `TRUSTED_HOSTS` 或 `TRUSTED_PROXY_IPS` 设为 `*`。

## 8. Bilibili 扫码登录

进入“账号”页面，点击网页扫码登录并在 Bilibili App 中确认。凭据保存在：

```text
CONFIG_DIR/bbdown/BBDown.data
```

完整 Cookie 不返回浏览器。不要公开 `CONFIG_DIR`、数据库、备份或 `docker/.env`。

## 9. 更新

```bash
cd /share/Container/bili-workspace/app
git pull --ff-only
./docker/build-and-start.sh
```

代码更新会重新构建镜像，但不会删除四个宿主机映射目录。配置模板的新字段会在启动时补入实际配置。

## 10. 停止与恢复

停止但保留数据：

```bash
docker compose --env-file docker/.env down
```

真正恢复时，先恢复 `CONFIG_DIR` 和 `MEDIA_DIR`，确认 PUID/PGID 可读写，再启动容器。

## 11. 常见问题

### 容器反复重启

检查：

- 四个目录是否存在且对 PUID/PGID 可写；
- 端口是否被占用；
- NAS 是否能访问首次构建所需下载站点；
- 域名是否在 `TRUSTED_HOSTS`；
- 反向代理来源 IP 是否正确；
- `CONFIG_DIR/bbdown` 中的程序是否可执行。

### 手机无法访问

确认：

- `BIND_IP` 不是 `127.0.0.1`；
- QNAP 防火墙允许局域网访问 `HTTP_PORT`；
- 手机和 NAS 路由可达；
- 访问 IP Host 时运行配置允许数字 IP Host；
- 登录初始化已完成。

### 浏览器不能播放

先尝试原文件。设备不支持 HEVC/AV1 或音频编码时，在作品详情中手动生成兼容播放版。软件转码会占用 NAS CPU。
