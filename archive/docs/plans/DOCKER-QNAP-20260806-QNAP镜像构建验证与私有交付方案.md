# QNAP Docker 镜像构建、验证与私有交付方案

- 状态：已完成
- 主责：从当前源码构建可由 QNAP Container Station 使用的真实 Linux 镜像，完成隔离验证并形成私有交付物
- 原待办：`DOCKER-QNAP-20260806`，已退出[当前待办](../../../docs/已知问题与待做需求.md)

## 1. 决策来源与目标

用户于 2026-08-06 决定先关闭 Windows/T-PROJECT 收口，再独立推进 Docker/QNAP。目标是让自有 QNAP 能通过镜像仓库拉取或 `docker save` 离线包导入当前源码构建的镜像，并使用三个独立持久化目录运行。

这是私有部署任务，不恢复正式发布能力，不创建新 tag、GitHub Release 或 GHCR 正式镜像；如未来需要公开或认证仓库发布，必须另行形成决策并取得发布与凭据使用授权。

用户在验收镜像证据后进一步决定：本轮只保留镜像打包与离线交付能力，不实施真实 QNAP 部署；打包流程进入活动运维手册，真实目录、账号、网络和上线方式等待未来新想法另行立项。本方案按这一最终边界关闭。

## 2. 已确认与待补输入

已确认：

1. 目标型号是 QNAP TS-453Bmini-8G；QNAP 官方规格为 Intel Celeron J3455、64 位 x86，因此目标平台为 `linux/amd64`；
2. 用户目标是让 Container Station 加载镜像包，本轮采用 `docker save` 离线 tar 包，不使用镜像仓库或认证凭据；
3. QNAP 官方 Container Station 3 指南确认镜像页可导入 `.tar`、`.tar.gz` 或 `.tgz`，也可使用 `docker load`。

QNAP 上三个共享目录、运行账号 UID/GID 和真实上线方式不再作为本方案待补输入；它们已随真实部署一起退出当前范围。

## 3. 已确认实施范围

- 复核 `docker/Dockerfile`、`docker/compose.yaml`、入口脚本、健康检查和构建脚本对目标架构的支持；
- 使用当前工作树构建真实项目镜像，不使用冻结的 V0.7.0 正式发布物冒充当前源码；
- 在仓库外隔离目录验证镜像元数据、非 root 用户、`/data/config`、`/data/userdata`、`/downloads`、只读根、健康检查、启动、停止和重启；
- 只使用测试配置和空白持久化目录，不使用真实 Cookie、Token、用户数据或 QNAP 生产目录；
- 根据确认的交付方式生成可复现的拉取说明或离线 tar 包，并记录平台、镜像 ID、大小和 SHA-256；
- 将已验证的镜像构建、隔离运行、`docker save/load`、校验和与 Container Station 导入边界收口到活动运维手册，并退出未确认的真实 QNAP 部署指南。

## 4. Linux、WSL 与浏览器验证边界

- Linux 行为优先在最终项目镜像内验证；只有镜像无法解释宿主 shell、权限或进程差异时，才考虑补装 WSL 开发依赖运行完整源码入口。
- Windows 收口中未运行的 7 个 Playwright 模块没有因镜像打包产生新的阻断证据；本轮未安装 Playwright/Chromium，也未启动浏览器进程。该事项不继续挂靠已完成方案，未来确有浏览器加固需求时重新形成任务。

## 5. 安全与交付约束

- 构建过程可以使用 Dockerfile 已声明的公共系统包、Python 包和固定 BBDown 下载源；不访问私有或认证网络。
- 构建和验证不得覆盖现有 QNAP 配置、持久化目录或仓库实际本地配置。
- 镜像启动仅绑定回环地址或隔离测试网络；只有用户明确提供 QNAP 目标后才执行到设备的传输或部署。
- 离线包默认写入仓库外明确交付目录，不写入 Git；大文件清理、覆盖或替换必须再次核对精确目标。

## 6. 验证与完成条件

- 测试层级：普通针对性验证，并包含真实镜像构建、隔离容器运行与交付物复载；未执行全量测试，也不提升为正式发布认证。
- 验证影响域：目标架构、镜像内容、非 root 边界、三个持久化挂载、只读根、健康检查、启动与重启、交付物身份和 Docker 打包运维说明。
- 具体验证项：以下六项完成条件；实际命令、镜像摘要、运行 ID、跳过项和证据路径在获得目标架构与交付方式后记录。

完成至少需要：

1. 目标平台的真实镜像构建成功，镜像架构与 QNAP 一致；
2. 容器以非零 UID/GID 启动，三个持久化目录可写且互相分离；
3. 健康检查通过，测试服务可以启动、停止和重启，持久化测试标记在重建容器后仍存在；
4. 交付物可以通过选定方式重新加载或拉取，并得到相同镜像 ID/摘要；
5. 当前运维入口给出准确的构建、隔离验证、离线打包、校验、复载和 Container Station 导入边界，并明确真实部署暂缓；
6. 用户验收实际证据并明确关闭真实部署范围后，按本次授权提交并推送仓库。

## 7. 实施结果

2026-08-06 已完成以下结果：

1. 使用 `docker/Dockerfile` 按 `linux/amd64` 构建 `bili-workspace:qnap-amd64-20260806`，最终镜像 ID 为 `sha256:2c55899e641e37a52b172688c48b11710cf95e59cbf95f8b2525d66b7def87aa`，镜像元数据为 `linux/amd64`、默认用户 `1000:1000`、大小 `620459810` 字节；最终缓存重建仍得到同一镜像 ID。
2. 隔离实例按 Compose 默认映射以 `uid=1000`、`gid=100` 运行，启用只读根、`cap_drop=ALL` 和 `no-new-privileges`；`/data/config`、`/data/userdata`、`/downloads` 均为独立可写 bind mount。
3. `/healthz` 返回 `ok=true`、版本 `0.7.0`、模式 `docker`；实例完成启动、停止、重新创建并再次健康，三个挂载中的测试标记在重建后均保留。
4. 仓库外交付物为 `D:\Projects\python\bili_workspace_test\20260806-qnap-amd64-image-01\results\bili-workspace-qnap-amd64-20260806.tar`，大小 `629012480` 字节（599.87 MiB），SHA-256 为 `2E42C726D46704390CB0E8150393F346354890A0EC0094362423FD887B49AB28`。
5. `docker load` 成功复载该 tar，复载后镜像 ID 仍为 `sha256:2c55899e641e37a52b172688c48b11710cf95e59cbf95f8b2525d66b7def87aa`。
6. 修订 `docker/build-and-start.sh` 与配置字段，增加 `BUILD_LOCAL=false`、`PULL_IMAGE=false` 的已导入镜像模式；Linux fixture 证明该模式只执行 `up -d --no-build`，不执行 pull，镜像缺失时会在启动前失败。
7. 最终将可复现打包流程收口到 `docs/运维/Docker镜像打包与离线交付.md`，删除混合了未确认设备部署方式的活动 QNAP 指南，并精简运维区的重复与失效材料。
8. 关闭候选的 Docker shell 语法验证通过，Docker/仓库结构定向 pytest 为 `27 passed`，源码边界与 Markdown 内部链接检查通过，文档机械一致性为 `0 warning(s)`，`git diff --check` 通过；完整镜像证据位于上述测试运行目录，汇总见 `results/validation-report.md`。

本轮未安装或运行 WSL 开发依赖、Playwright/Chromium，未连接真实 QNAP、未使用真实数据或凭据，也未执行全量测试、正式认证、PR 或正式发布。用户已单独授权在关闭后完成一次仓库 commit 和 push。

用户已验收打包证据并将真实设备部署移出当前范围；完成条件全部满足。

## 8. 收尾与联合复核

- 本方案主责与完成证明：由目标架构镜像、隔离运行证据、健康状态、持久化重建验证和可复现交付物共同承接。
- 关闭时的状态消费者：`docs/已知问题与待做需求.md`、Docker 镜像打包运维手册、测试结果记录和归档索引。
- 关联方案：`TEST-ENTRY-20260803` 只承接已完成的 Windows/T-PROJECT 收口；本方案不改写其历史 blocked、skipped 或 passed 结果。
- 验收结果：镜像与离线包证据已获用户接受；真实部署暂缓，不保留活动待办。
- 关闭边界：本次只额外授权完成一次仓库 commit 和 push；仍不授权 PR、tag、GitHub Release、GHCR、真实设备写入或正式发布。
