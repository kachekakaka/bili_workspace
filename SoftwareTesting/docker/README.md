# T-DOCKER Docker 镜像构建验证

- Registry ID：`T-DOCKER`
- 执行类别：`affected_only`
- 触发条件：`docker/`、根 `.dockerignore`、应用或前端镜像输入、`app/defaults/`、运行依赖锁、镜像内许可材料，或者 `.github/workflows/ci.yml`、`.github/workflows/docker-image.yml` 中的 Docker 验证发生变化。
- 输入：当前候选源码、`docker/Dockerfile`、根 `.dockerignore` 与 Docker 构建上下文、`requirements/runtime.lock`、`THIRD_PARTY_NOTICES.md`、`LICENSES/` 及两个直接 workflow 消费者。
- 工作目录：仓库根目录。
- 唯一职责：验证当前 Docker 镜像能够按声明架构实际构建，并证明验证过程不发布镜像；不承接 Python 逻辑测试、Windows 启动器的固定 amd64 离线导出或正式发布。

## 现有消费者与架构边界

| 消费者 | 构建边界 | 稳定断言 |
| --- | --- | --- |
| `.github/workflows/ci.yml` 的 `docker-validation` 作业 | 使用 `docker/Dockerfile` 和当前根构建上下文执行单架构 `linux/amd64` 构建，再从本地验证镜像运行版本冒烟 | 镜像构建成功，容器内 `app.__version__` 为当前版本；镜像只使用任务内标签，不推送 |
| `.github/workflows/docker-image.yml` | 使用 Buildx 与 QEMU 构建 `linux/amd64,linux/arm64`，`push: false` | 两个声明架构均完成构建求值，不创建或推送正式镜像 |
| [Docker 镜像打包与离线交付手册](../../docs/运维/Docker镜像打包与离线交付.md) | 本地按目标平台执行构建、隔离运行、离线打包和复载 | `Create`/`Record` 只接受 `T-DOCKER` 并写最小 Docker 交接记录；只有必要阶段实际成功后才能记录 `passed` |

Python 持久化、迁移和发布策略测试属于 T-PROJECT，不在 Docker job 中重复；它们不能替代真实 Docker 构建。T-LAUNCHER 负责启动器面向 `linux/amd64` 的 Docker 导出三件套及其事务、身份与恢复协议，也不替代本项的一般项目镜像构建。

## 选择与环境

T-DOCKER 不属于每次完整检查都固定执行的 `full` 项。候选命中触发条件时，全量测试或正式认证才按实际影响选择本项；未命中时记录为 `not_run`，不能据其他静态检查宣称通过。

本地手工入口与两个 workflow 消费者属于同一个 `T-DOCKER`，不创建派生测试 ID。真实 Docker build/run/save/load 会启动进程、读取公开构建输入并产生镜像、容器和仓库外产物，必须在执行前取得相应授权；静态检查或本手册存在本身不能替代动态结果。

专用多架构 workflow 在 `main` push 和 pull request 命中同一组精确路径时运行；普通 PR 不因无关文件变化执行 T-DOCKER。

实际执行需要可用的 Docker Engine；多架构阶段还需要 Buildx 和 QEMU。构建会读取公开基础镜像、系统包和运行依赖，并可能产生任务拥有的构建缓存、验证镜像和短生命周期容器。有界公开只读联网必须满足[测试安全](../SAFETY.md)；认证、私有资源、上传、付费、明显大规模下载或特殊环境使用仍按项目授权边界处理。

## 结果语义

- `passed`：本次影响范围要求的单架构或多架构阶段全部执行，构建及对应稳定断言均成功，且没有发布镜像。
- `failed`：Docker 已进入构建或容器冒烟的可判定阶段，但构建、架构求值、版本断言或不发布约束失败。
- `blocked`：缺少已要求的 Docker Engine、Buildx、QEMU、公开构建输入或相应授权，尚未进入可判定阶段。
- `inconclusive`：执行被中断、运行器异常，或适用架构／断言被跳过而证据不完整。
- `not_run`：没有执行；workflow 定义存在、静态 Docker 测试通过或其他平台构建成功都不能替代本项结果。

动态镜像 ID、运行时间、缓存身份和候选摘要由 CI 输出或本地最小交接记录承接，不写入本活动入口。

## 清理边界

托管 CI 的任务内镜像、容器和缓存由对应临时 runner 生命周期承接。本地执行时只能清理本次命令创建且所有权可验证的精确容器、标签和输出；不得使用通用 prune、按名称宽泛删除、操作其他运行或把清理扩展到真实部署。
