# 测试安全

## 隔离运行目录

T-PROJECT 默认在系统临时目录的 `bili_workspace_test` 下创建唯一 run；可以用 `BILI_TEST_ROOT` 覆盖，但测试根必须位于仓库外且不能包含仓库。每个 run 是测试根的直接子目录，并带 `.bili-workspace-test-run.json` 最小所有权标记；标记只用于校验项目、工作区、测试根和精确路径，不是长期结果 schema。

配置、userdata、下载、HOME、缓存、临时文件、Python 字节码、pytest basetemp、日志和浏览器 profile 必须位于本次 run。`tools/t_project_isolation.py` 只提供 `create`、`validate` 和 `cleanup`：清理前重新验证所有权、直接父子关系、仓库外 containment 和重解析点，只删除精确 run，不删除测试根或相邻内容。

本地 `scripts/dev/verify-source.sh` 在结果与失败诊断输出后清理自己的 run。CI `scripts/dev/run-playwright-phase.sh` 保留 run 到 `.github/workflows/ci.yml` 的 `if: always()` Artifact 上传结束，再由临时 runner 回收；不能在上传前调用 cleanup。普通测试不维护结果文件、期限或 GC。

T-DOCKER 手工入口使用 `scripts/windows/new-test-run.ps1` 的既有 `Create`/`Record` 调用形状，只接受 `T-DOCKER`，并写最小 Docker 交接记录。它不创建 T-PROJECT 证据，也不读取、迁移或删除既有仓库外记录。

## 真实数据与进程

- 除下述 `T-BILIBILI-LIVE` 窄例外外，禁止读取、修改或复制真实配置、数据库、Cookie、Token、媒体、账号资料和其他用户数据。
- 项目完整自检只启动本次命令直接拥有的 Python、Node、回环服务和无头测试浏览器子进程，不启动真实应用服务、用户浏览器或容器。
- 只管理本次启动并持有句柄的进程，禁止按进程名称批量结束。
- fixture、缓存、日志和输出必须位于隔离 run；不得写入真实持久化目录。
- 需要认证、私有资源、上传、外部写入、费用、明显大规模下载或特殊环境的测试必须单独声明并取得授权。

### T-BILIBILI-LIVE 窄例外

- 只有调用者显式传入的凭据源根同时含有有效 `.bili-workspace-live-test.json` 和普通 `config/bbdown/BBDown.data` 时才可选择；运行器不能创建标记、扫描其他目录或读取来源数据库、配置与媒体。
- Windows 入口必须显式设置仓库外、凭据源外且不位于 `%LOCALAPPDATA%` 的绝对 `BILI_TEST_ROOT`。每次只创建一个带通用所有权标记和 `results/summary.json` 的新 run，产品、工具、浏览器 profile、下载和日志全部位于该 run。
- 真实链固定 15 分钟、run 增长 2 GiB、开始下载前 5 GiB 可用空间和 8 个 BV 上限；只停止本次持有句柄的进程。成功停止后删除 run 内所有 `BBDown.data`，非通过 run 整体保留。
- 原始公开响应可以保存在 run，但不得记录请求头、Cookie、二维码载荷、原始 `/nav` 账号响应、WBI 签名查询值、响应头、HAR 或完整网络流量；这些产物和授权标记永不进入 Git。
- 满 72 小时只表示 run 可由维护者指定清理；普通运行不自动删除。列举是只读动作，删除前重新验证所有权、年龄、直接父子关系、重解析点及工作区/凭据源 containment。

## 无头浏览器

- Playwright 是 T-PROJECT full 的必需阶段，只复用已存在的 Playwright Chromium、Chrome、Edge 或 Chromium；不安装、下载或更新浏览器。
- `BILI_PLAYWRIGHT_CHROMIUM` 只允许指向既有普通可执行文件。浏览器使用本次 run 下的新 profile、缓存和临时目录，不复用系统用户 profile、登录会话或已打开实例。
- 浏览器测试只访问测试直接拥有的回环 HTTP 服务和本地静态资源，不访问真实 Bilibili、真实部署地址或其他外部网络。
- 缺少可用浏览器时记录 `blocked`，不得按名称结束现有浏览器或临时下载来继续。

## 敏感信息

测试只使用虚构凭据和隔离数据。控制台、Artifact、失败输出和交接摘要不得回显秘密或原始真实运行现场。
