# GitHub 仓库网页搭建、首次发布与协作分工指南

> 适用场景：项目所有者先在 GitHub 网页创建仓库，随后由开发者或 AI 助手整理源码、配置 CI、Docker、发布流程并持续维护。  
> 示例项目：`bili_workspace`。本文也可直接复用于其他 Windows、Python、Docker、NAS 项目。

---

## 1. 最终目标

一个可长期维护的 GitHub 仓库，应满足以下要求：

```text
网页创建仓库
→ 完成必要权限和安全设置
→ 标准 Git 提交完整源码
→ CI 自动测试
→ Docker/GHCR 自动构建
→ 全新 git clone 可运行
→ 后续只需 git pull 更新
```

不应依赖：

```text
Base64 源码分片
Actions 自解包恢复源码
把真实配置、Cookie、数据库上传到 Git
每次升级重新复制配置和媒体目录
不可迁移的 .venv
```

---

## 2. 工作分工总览

### 2.1 项目所有者必须手工完成的事项

有些操作涉及账号身份、仓库所有权、付费计划、包公开性或浏览器确认，必须由仓库所有者完成：

1. 在 GitHub 网页创建仓库；
2. 选择仓库名称、可见性和所有者；
3. 给协作工具或 GitHub App 授权；
4. 配置 GitHub Actions 权限；
5. 首次生成容器包后，决定 GHCR 包是否公开；
6. 如需保护 `main`，在网页创建 Ruleset；
7. 在自己的电脑上完成 Git 凭据或 SSH 登录；
8. 确认敏感信息、域名、NAS 路径和公开范围。

### 2.2 AI 助手或开发者负责的事项

1. 审计和整理源码；
2. 删除敏感信息和临时文件；
3. 编写 `.gitignore`、`.gitattributes` 和 `.dockerignore`；
4. 设计默认配置与真实配置分离；
5. 创建 CI、Docker、发布和验证脚本；
6. 建立分支、提交、Pull Request 和版本标签；
7. 执行编译、静态检查、测试和安全扫描；
8. 重新克隆远端仓库进行验收；
9. 后续根据需求持续提交更新；
10. 明确报告尚未验证或必须在实机完成的项目。

---

# 3. 第一次必须在 GitHub 网页手工完成的操作

## 3.1 创建仓库

在 GitHub 网页右上角选择：

```text
+ 
→ New repository
```

填写：

```text
Owner：你的个人账号或组织
Repository name：例如 bili_workspace
Description：一句话说明用途
Visibility：Public 或 Private
```

### 从已有源码或 Git 历史导入时

建议创建一个**空仓库**，不要勾选：

```text
Add a README file
Add .gitignore
Choose a license
```

原因是已有项目通常已经包含这些文件。网页额外生成一次初始提交，会导致本地与远端历史分叉，首次发布可能需要合并或改写历史。

### 新项目完全从零开始时

可以勾选 README 和 License，但后续源码必须基于这个远端提交继续开发，不要再用另一个不相关的本地初始历史强制覆盖。

---

## 3.2 选择仓库可见性

### Public

适合：

```text
开源项目
公开下载和部署
公开 GHCR 镜像
希望 NAS 无登录拉取镜像
```

注意：

- 任何人都能看到源码、提交历史、Issues 和 Actions 日志；
- 绝不能提交 Cookie、Token、密码、数据库、私有域名配置或个人媒体；
- 已公开的秘密即使之后删除，仍可能存在于 Git 历史、缓存或镜像层中。

### Private

适合：

```text
内部项目
包含商业逻辑
暂不准备公开
```

注意：

- 私有 GHCR 镜像通常需要登录后拉取；
- 协作者、GitHub App、Actions 和部署机器都需要相应权限；
- 以后从 Public 改回 Private、处理 Fork 或包可见性时要谨慎。

---

## 3.3 给协作工具授权

推荐做法：

```text
GitHub 账号 Settings
→ Applications
→ Installed GitHub Apps
→ 选择对应应用
→ Configure
→ Only select repositories
→ 勾选目标仓库
```

权限尽量限制在单个仓库，而不是长期开放全部仓库。

最低常用权限：

```text
Contents：Read and write
Pull requests：Read and write
Issues：按需
Actions：读取状态；修改工作流时需要相应权限
Administration：只有修改仓库设置时才需要
```

不要在聊天中发送：

```text
GitHub 密码
Personal Access Token
SSH 私钥
浏览器 Cookie
设备登录验证码
```

---

## 3.4 开启 GitHub Actions

仓库网页进入：

```text
Settings
→ Actions
→ General
```

### Actions permissions

项目需要使用：

```text
actions/checkout
actions/setup-python
actions/setup-node
actions/upload-artifact
docker/login-action
docker/setup-buildx-action
docker/build-push-action
docker/metadata-action
```

可选择：

```text
Allow all actions and reusable workflows
```

或只允许 GitHub 官方、验证发布者和明确列出的 Actions。

对于长期公开项目，建议后续进一步限制，并把第三方 Action 固定到完整 commit SHA。

### Workflow permissions

普通只读 CI 可以使用：

```text
Read repository contents and packages permissions
```

当工作流需要执行以下操作时：

```text
提交生成文件回 main
创建 Release
上传 Release 资产
推送 GHCR 镜像
更新标签
```

需要选择：

```text
Read and write permissions
```

同时工作流文件中仍应按最小权限声明，例如：

```yaml
permissions:
  contents: write
  packages: write
```

不要长期给每个工作流 `write-all`。

---

## 3.5 GHCR 容器包设置

当工作流首次推送：

```text
ghcr.io/你的账号/项目名:latest
```

GitHub 个人主页或仓库右侧会出现 Packages。

如果希望 QNAP 或其他 NAS **无需登录即可拉取镜像**：

```text
Packages
→ 选择对应容器包
→ Package settings
→ Danger Zone
→ Change visibility
→ Public
```

重要注意：

- GHCR 公共包可以匿名拉取；
- 包改为 Public 后，通常不能再恢复为 Private；
- 先确认镜像中没有秘密、真实配置、Cookie、数据库或私有证书，再公开；
- 若保持 Private，NAS 需要执行 `docker login ghcr.io`。

---

## 3.6 分支保护或 Ruleset

首次导入源码和修复历史阶段，不建议立刻启用严格规则，否则可能阻止必要的首次推送或 Actions 生成文件。

第一次正式源码、CI 和运行包都验证成功后，再进入：

```text
Settings
→ Rules
→ Rulesets
→ New branch ruleset
```

推荐目标：

```text
Default branch / main
```

推荐规则：

```text
阻止删除 main
阻止 force push
要求 Pull Request
要求 CI 状态检查通过
可选：要求线性历史
```

个人独立项目可以允许仓库管理员在紧急情况下绕过，但每次绕过都应有说明和备份。

---

## 3.7 本机 Git 凭据

网页仓库创建完成后，项目所有者的电脑仍需能执行标准 Git 操作。

HTTPS 方式：

```bat
git clone https://github.com/OWNER/REPOSITORY.git
```

Git for Windows 通常会调用 Git Credential Manager 打开浏览器授权。

SSH 方式：

```bash
git clone git@github.com:OWNER/REPOSITORY.git
```

需要提前在 GitHub 账号中登记 SSH 公钥。

验证权限：

```bash
git ls-remote https://github.com/OWNER/REPOSITORY.git refs/heads/main
```

能够返回提交 SHA，说明读取正常。实际推送前再用测试分支确认写权限。

---

# 4. 仓库所有者完成网页设置后，需要告诉 AI 助手什么

建议一次性提供以下信息：

```text
仓库地址
仓库可见性
默认分支名
是否允许 Actions 写回仓库
是否需要 GHCR
GHCR 是否计划公开
是否需要 Release
支持的平台：Windows / Linux / amd64 / arm64
实际配置和数据必须保存到哪里
允许提交到 Git 的大型文件类型
哪些目录绝不能上传
发布和版本号规则
```

例如：

```text
仓库：https://github.com/example/bili_workspace
默认分支：main
仓库：Public
Actions：允许 contents/packages 写入
GHCR：需要，发布后设为 Public
Windows：git pull 后直接 start.bat
Docker：amd64 + arm64
实际配置：config 目录，禁止提交
NAS 数据：四个 bind mount，禁止提交
```

---

# 5. AI 助手收到仓库后应完成的工作

## 5.1 先做源码和敏感信息审计

扫描：

```text
.env
*.key
*.pem
Token
Cookie
BBDown.data
数据库
日志
下载媒体
浏览器会话
管理员初始化令牌
开发机绝对路径
```

发现真实凭据时：

1. 停止发布；
2. 从工作区移除；
3. 加入 `.gitignore`；
4. 如果已经推送，立即轮换凭据；
5. 必要时清理 Git 历史。

---

## 5.2 建立标准仓库结构

推荐：

```text
.github/workflows/      CI、运行时构建、Docker 构建
app/                    后端
web/                    前端
tests/                  测试
tools/                  安装、校验、迁移和发布工具
docker/                 Docker 入口和部署脚本
docs/                   部署、配置、需求和恢复文档
config/*.default        默认配置模板
vendor/                 经过校验的可分发运行时资产
README.md
CHANGELOG.md
LICENSE
THIRD_PARTY_NOTICES.md
.gitignore
.gitattributes
.dockerignore
Dockerfile
compose.yaml
```

---

## 5.3 配置文件必须与源码分离

Git 只提交模板：

```text
.env.default
config/config.json.default
config/runtime.env.default
docker/.env.default
```

实际运行时生成：

```text
.env
config/config.json
config/runtime.env
docker/.env
```

启动或更新时执行：

```text
实际文件不存在
→ 从 .default 创建

实际文件已存在
→ 保留用户值

新版 default 增加字段
→ 递归补充缺失字段

实际文件有额外字段
→ 不删除
```

实际配置、数据库和 NAS 路径不能因 `git pull` 或容器重建被覆盖。

---

## 5.4 设计“开箱即用”方式

### 不推荐直接提交 `.venv`

`.venv` 常包含：

```text
创建机器绝对路径
Python ABI
平台相关启动器
缓存
本机安装状态
```

跨目录、跨 Python 小版本或跨系统不可靠。

### 更可靠的 Windows 开箱即用方案

```text
Portable Python
+ 固定依赖
+ BBDown
+ FFmpeg
→ 构建为经过 SHA-256 校验的运行包
→ 每个 Git 对象小于 100 MiB
→ start.bat 自动校验并解压
```

用户最终只需：

```bat
git pull --ff-only origin main
start.bat
```

### Docker 开箱即用方案

```text
GitHub Actions
→ 构建 linux/amd64 与 linux/arm64
→ 推送 GHCR
→ QNAP docker compose pull/up
```

所有运行数据必须映射到宿主机：

```text
/data/config
/data/media
/data/cache
/data/tmp
```

---

## 5.5 配置自动化测试

至少包括：

```text
源码结构和敏感信息扫描
Python compileall
Ruff
pytest
前端 JavaScript 语法
Docker Compose 配置检查
Docker 镜像构建
Windows 运行时哈希与解包测试
```

每个重要版本必须在**全新克隆目录**验证，而不能只在开发目录验证。

---

## 5.6 使用分支和 Pull Request

推荐流程：

```text
main
└─ feature/xxx 或 agent/xxx
   ├─ 修改
   ├─ 测试
   ├─ 提交
   └─ Pull Request
```

PR 中应写明：

```text
改了什么
为什么改
配置是否迁移
是否影响数据库
测试结果
仍需实机验证的内容
回滚方式
```

只有 CI 通过后再合并到 `main`。

---

# 6. 首次正式发布的正确流程

## 6.1 推荐流程

```text
本地或工作分支完成源码
→ 扫描敏感信息
→ 运行全部测试
→ git commit
→ 推送分支
→ 创建 PR
→ CI 通过
→ 合并 main
→ 推送 tag
→ 构建 Release / GHCR
→ 全新 clone 验证
```

## 6.2 已存在损坏远端时

先备份旧分支：

```bash
git push origin OLD_SHA:refs/heads/archive/broken-bootstrap-YYYYMMDD-HHMMSS
```

替换 `main` 时只允许：

```bash
git push --force-with-lease
```

禁止直接：

```bash
git push --force
```

`--force-with-lease` 会检查远端是否仍是预期提交，避免覆盖别人刚推送的新工作。

## 6.3 发布后必须重新克隆

```bash
git clone --depth 1 --branch main REPOSITORY_URL verify-clone
```

检查：

```text
根目录是完整源码
没有 bootstrap/source.part*
没有真实配置和凭据
默认配置模板存在
start/verify/update 脚本存在
CI 文件存在
版本号正确
运行时资产哈希正确
```

此前项目发布日志已经证明，`dry-run → 备份旧分支 → force-with-lease → 推送 tag → fresh clone` 是一条可审计且可回滚的发布链路。

---

# 7. 大文件和二进制文件注意事项

GitHub 对普通 Git 对象存在硬限制：

```text
单个对象：100 MiB
单次 push：2 GiB
```

推荐最大单个普通 Git 文件远低于硬限制。

可选方案：

### 方案 A：拆成多个独立运行包

适合：

```text
Portable Python
媒体工具
模型分片
固定依赖
```

要求：

```text
每个文件小于 100 MiB
有整体 SHA-256
压缩包内部有逐文件清单
解压时防路径穿越、重复路径和符号链接
```

### 方案 B：Git LFS

适合经常更新的大型二进制，但要注意：

```text
需要客户端安装 Git LFS
存在存储和流量配额
克隆时需要额外下载 LFS 对象
部分 NAS 或离线环境体验较差
```

### 方案 C：GitHub Release

适合：

```text
安装包
完整 ZIP
离线环境包
Git Bundle
恢复包
```

### 方案 D：GHCR

适合：

```text
Docker 镜像
amd64/arm64 多架构部署
```

不要使用：

```text
把压缩包转成 Base64 文本
拆成大量 source.part 文件
依赖 Actions 在仓库内自解包并提交源码
```

这种方法难以审查、容易截断、容易触发无限工作流，也不适合长期维护。

---

# 8. 安全注意事项

## 8.1 绝不能提交

```text
真实 .env
数据库
Cookie
BBDown.data
管理员密码
初始化令牌
私钥和证书私钥
下载视频
任务日志中的敏感字段
浏览器导出临时文件
NAS 真实备份
```

## 8.2 Actions 最小权限

工作流仅测试：

```yaml
permissions:
  contents: read
```

工作流提交生成文件：

```yaml
permissions:
  contents: write
```

工作流推送 GHCR：

```yaml
permissions:
  contents: read
  packages: write
```

不要无理由使用：

```yaml
permissions: write-all
```

## 8.3 第三方 Action

长期项目建议：

```text
优先 GitHub 官方 Action
优先验证发布者
固定到完整 commit SHA
定期审查版本
```

## 8.4 Public 仓库日志

Actions 输出中不要打印：

```text
环境变量全集
Cookie
Token
数据库内容
完整配置
私有域名凭据
```

---

# 9. 推荐的日常更新流程

## 所有者

平时只需：

```bat
git pull --ff-only origin main
start.bat
```

QNAP：

```bash
git pull --ff-only origin main
./docker/build-and-start.sh
```

## AI 助手

每次需求：

```text
读取当前 main
→ 建新分支
→ 修改代码和测试
→ 更新默认配置和迁移
→ 运行验证
→ 创建 PR
→ 报告变更和风险
```

## 合并后

```text
CI 通过
→ 合并
→ 用户 git pull
→ 实机验收
→ 发现问题后继续提交修复
```

---

# 10. `bili_workspace` 推荐网页设置

## 仓库

```text
名称：bili_workspace
默认分支：main
可见性：Public
```

## Actions

```text
Actions：Enabled
Workflow permissions：Read and write permissions
```

原因：

```text
Windows 集成运行时工作流需要提交生成的 pack 文件
Docker 工作流需要推送 GHCR
普通 CI 仍在 workflow 内使用最小权限
```

## Packages

```text
ghcr.io/kachekakaka/bili_workspace
```

首次镜像生成并确认无敏感信息后：

```text
Package visibility：Public
```

这样 QNAP 可以匿名拉取。

## Ruleset

完成首次稳定发布后再开启：

```text
目标：main
阻止删除
阻止 force push
要求 PR
要求 CI 通过
管理员保留紧急绕过能力
```

## 实际数据

必须保持未跟踪：

```text
config/config.json
config/runtime.env
docker/.env
/data/config
/data/media
/data/cache
/data/tmp
BBDown.data
SQLite
下载媒体
```

---

# 11. 常见错误与处理

## 仓库只有几个分片文件

原因：

```text
使用了 Base64/Actions 恢复方案
```

处理：

```text
停止恢复 Workflow
直接标准 Git 提交源码树
全新 clone 验证
```

## Actions 无权提交文件

检查：

```text
Settings
→ Actions
→ General
→ Workflow permissions
→ Read and write permissions
```

并确认 workflow 内有：

```yaml
permissions:
  contents: write
```

## GHCR 拉取要求登录

原因：

```text
包仍为 Private
```

处理：

```text
把包设为 Public
```

或在 NAS 登录：

```bash
docker login ghcr.io
```

## 大文件被拒绝

检查：

```text
是否超过 100 MiB
是否应该拆包
是否应该使用 LFS、Release 或 GHCR
```

## 配置被更新覆盖

说明设计错误。应改为：

```text
.default 进入 Git
实际配置被 .gitignore
升级时只补字段
```

## CI 一直发失败邮件

先停止错误工作流，不要反复 Re-run。修复 workflow 或删除无效 workflow 后，再按需要调整通知设置。

---

# 12. 首次搭建检查清单

## 所有者手工操作

- [ ] GitHub 账号已启用安全登录和恢复方式；
- [ ] 已创建空仓库；
- [ ] 已决定 Public 或 Private；
- [ ] 已给协作 App 仅授权目标仓库；
- [ ] Actions 已启用；
- [ ] 需要写回时已设置 Read and write permissions；
- [ ] 本机 Git 凭据可正常 push；
- [ ] 已决定是否需要 GHCR；
- [ ] 已决定 GHCR 是否公开；
- [ ] 首次源码稳定后再启用 Ruleset；
- [ ] 已明确哪些数据禁止上传。

## AI 助手或开发者

- [ ] 完成敏感信息扫描；
- [ ] 完成标准源码目录；
- [ ] `.gitignore`、`.gitattributes`、`.dockerignore` 已建立；
- [ ] `.default` 配置机制已实现；
- [ ] CI 已建立；
- [ ] Docker/GHCR 流程已建立；
- [ ] 大文件方案符合 100 MiB 限制；
- [ ] 所有二进制有 SHA-256；
- [ ] 已运行编译、静态检查和测试；
- [ ] 已创建 PR 并说明风险；
- [ ] 已从远端全新 clone 验证；
- [ ] 已提供回滚和备份方式。

---

# 13. 最简协作模板

项目所有者可以直接把下面内容发给 AI 助手：

```text
请为这个项目建立并维护 GitHub 仓库。

仓库：
默认分支：
可见性：

目标：
- 全新 clone 后可以：
- Windows 更新方式：
- Docker/NAS 更新方式：

GitHub 设置：
- Actions 是否允许写：
- 是否使用 GHCR：
- GHCR 是否公开：
- 是否需要 Release：

数据边界：
- 必须提交：
- 禁止提交：
- 持久化目录：

质量要求：
- 编译：
- 静态检查：
- 测试：
- 实机验证：

发布要求：
- 版本号：
- 标签：
- 需要的发布资产：
```

---

# 14. 结论

正确的 GitHub 仓库搭建，不是“把文件传上去”这么简单，而是明确三层边界：

```text
账号和仓库设置
→ 所有者手工控制

源码、测试、Docker 和发布流程
→ AI 助手或开发者维护

真实配置、凭据、数据库和媒体
→ 永远留在运行环境和持久化目录
```

推荐的长期模式是：

```text
所有者只做一次网页授权和仓库设置
AI 助手通过分支与 PR 持续更新
CI 自动验证
用户 git pull 后直接使用
```

这样才能做到可审查、可回滚、可恢复、可持续维护。
