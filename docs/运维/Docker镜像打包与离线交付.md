# Docker 镜像打包与离线交付

## 1. 当前范围

本手册只承接当前源码的 Linux 镜像构建、隔离验证、`docker save` 离线打包、校验和复载。真实 QNAP 目录、账号权限、网络入口和上线方式暂不在当前范围；形成新的部署想法后再单独决策。

私有离线包不是正式发布物。项目仍不创建新版本 tag、GitHub Release 或 GHCR 正式镜像，也不使用冻结的 V0.7.0 镜像冒充当前源码。

## 2. 目标平台与命名

先按目标设备 CPU 选择平台：

```text
64 位 Intel / AMD 处理器  → linux/amd64
64 位 ARM 处理器          → linux/arm64
```

[QNAP 官方规格](https://www.qnap.com/en-us/product/ts-453bmini/specs/package)显示 TS-453Bmini 使用 Intel Celeron J3455 和 64 位 x86 架构，因此该型号使用 `linux/amd64`。

私有镜像使用明确、不可复用的标签，例如：

```text
bili-workspace:qnap-amd64-YYYYMMDD
```

不要把不同源码构建结果反复覆盖成同一标签，也不要使用 `latest` 表示已经验证的私有交付物。

## 3. 构建与元数据检查

在仓库根目录执行：

```bash
docker build --pull \
  --platform linux/amd64 \
  --tag bili-workspace:qnap-amd64-YYYYMMDD \
  --file docker/Dockerfile \
  .

docker image inspect bili-workspace:qnap-amd64-YYYYMMDD \
  --format '{{.Id}} {{.Os}}/{{.Architecture}} {{.Config.User}} {{.Size}}'
```

至少确认：

- 平台与目标设备一致；
- 镜像默认用户不是 root；
- `/data/config`、`/data/userdata` 和 `/downloads` 均声明为持久化目录；
- 入口和健康检查存在；
- 镜像 ID、字节大小和构建日期进入验证记录。

Dockerfile 可以使用其中已经固定的公共 Debian、Python 和 BBDown 下载源，但不得加入私有凭据或真实运行数据。

## 4. 仓库外隔离运行验证

使用项目隔离入口创建仓库外空白运行目录，分别映射配置、运行数据和下载媒体。示例使用 PowerShell：

```powershell
$runRoot = & .\scripts\windows\new-test-run.ps1 -Action Create

docker run --detach --rm `
  --name bili-workspace-image-check `
  --platform linux/amd64 `
  --user 1000:100 `
  --publish 127.0.0.1::3398 `
  --read-only `
  --tmpfs /tmp:rw,noexec,nosuid,size=256m `
  --cap-drop ALL `
  --security-opt no-new-privileges:true `
  --env BILI_MIN_FREE_GIB=0 `
  --mount "type=bind,source=$runRoot\config,target=/data/config" `
  --mount "type=bind,source=$runRoot\userdata,target=/data/userdata" `
  --mount "type=bind,source=$runRoot\downloads,target=/downloads" `
  bili-workspace:qnap-amd64-YYYYMMDD
```

检查：

```powershell
docker inspect bili-workspace-image-check --format '{{json .State.Health}}'
docker exec bili-workspace-image-check id
docker inspect bili-workspace-image-check --format '{{json .Mounts}} {{.HostConfig.ReadonlyRootfs}}'
docker port bili-workspace-image-check 3398/tcp
```

完成条件：健康状态为 `healthy`；实际 UID/GID 均非零；三个 bind mount 相互独立且可写；根文件系统只读。停止并用相同目录重新创建容器后，配置、数据库和三个目录中的测试标记仍应存在。

验证结束后停止精确命名的测试容器：

```powershell
docker stop --timeout 45 bili-workspace-image-check
```

仓库外测试目录默认保留作为证据，不自动删除。

## 5. 生成离线包与校验和

Windows PowerShell：

```powershell
$artifact = Join-Path $runRoot 'results\bili-workspace-qnap-amd64-YYYYMMDD.tar'
docker save --output $artifact bili-workspace:qnap-amd64-YYYYMMDD
Get-Item -LiteralPath $artifact | Select-Object FullName, Length
Get-FileHash -Algorithm SHA256 -LiteralPath $artifact
```

Linux：

```bash
docker save -o bili-workspace-qnap-amd64-YYYYMMDD.tar \
  bili-workspace:qnap-amd64-YYYYMMDD
sha256sum bili-workspace-qnap-amd64-YYYYMMDD.tar
```

tar 包写入仓库外受控目录，不进入 Git。交付时同时提供镜像名、标签、平台、镜像 ID、tar 字节大小和完整 SHA-256。

## 6. 复载验证

在保留原镜像的情况下，`docker load` 可以验证 tar 结构、配置和标签可被 Docker 解析：

```powershell
docker load --input $artifact
docker image inspect bili-workspace:qnap-amd64-YYYYMMDD `
  --format '{{.Id}} {{.Os}}/{{.Architecture}} {{.Config.User}} {{.Size}}'
```

```bash
docker load -i bili-workspace-qnap-amd64-YYYYMMDD.tar
docker image inspect bili-workspace:qnap-amd64-YYYYMMDD \
  --format '{{.Id}} {{.Os}}/{{.Architecture}} {{.Config.User}} {{.Size}}'
```

复载后的镜像 ID 必须与打包前一致。不要为了复载测试删除仍承担验证或回退用途的本地镜像。

完成整轮验证后，通过同一隔离入口把最终状态写入 `results/result.json`：

```powershell
& .\scripts\windows\new-test-run.ps1 `
  -Action Record `
  -RunRoot $runRoot `
  -Status passed `
  -ExitCode 0 `
  -Message '镜像构建、隔离运行、离线打包与复载验证通过。'
```

## 7. Container Station 导入边界

[QNAP Container Station 3 官方指南](https://www.qnap.com/en-us/how-to/tutorial/article/how-to-use-container-station-3)说明“镜像”页支持导入 `.tar`、`.tar.gz` 和 `.tgz`；也可以通过 SSH 执行 `docker load`。

导入后如需让现有启动脚本只使用本地镜像，应设置：

```env
BILI_IMAGE=bili-workspace:qnap-amd64-YYYYMMDD
BUILD_LOCAL=false
PULL_IMAGE=false
```

该模式会先确认本地镜像存在，再执行 `up -d --no-build`，不会访问镜像仓库或隐式重建。真实共享目录、PUID/PGID、端口、反向代理、备份窗口和上线步骤留给未来部署方案，不由本手册推定。

每个新的源码候选和离线包都必须重新完成与其身份绑定的验证，并生成新的 SHA-256 校验和；归档中的旧结果只作历史证据，不能复用于新候选或新包。
