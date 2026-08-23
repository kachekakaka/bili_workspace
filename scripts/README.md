# 辅助脚本

Windows 日常用户入口只有仓库跟踪的 `dist/bili-workspace-launcher-0.7.0.exe`；根目录不再保留启动或部署自检批处理。

```text
scripts/windows/build-launcher.bat   使用根目录唯一 .venv 构建并自检规范 EXE
scripts/windows/new-test-run.ps1     创建并记账带 Registry TestId 的仓库外共享运行目录
scripts/dev/verify-source.sh         Linux/macOS/CI 源码完整自检入口
scripts/dev/run-playwright-phase.sh  CI 内部 T-PROJECT 浏览器阶段消费者
```

`build-launcher.bat` 是开发者构建入口，不是第二套日常启动链。网络、局域网服务器模式和 Bilibili 登录由启动器及 Web 界面管理。Linux/macOS 开发环境使用：

```bash
python -m pip install -r requirements/dev.lock
sh scripts/dev/verify-source.sh
```

PowerShell 共享帮助器的 `Create` 和 `Record` 都必须显式传入 `-TestId`，例如 T-PROJECT 使用 `-TestId T-PROJECT`，Docker 手工验证使用 `-TestId T-DOCKER`。新建证据使用 schema v2；旧 schema v1 只能继续按隐式 `T-PROJECT` 记录。T-PROJECT 的 Linux/macOS/CI 入口继续使用专用 Python 帮助器，调用参数不变。

源码完整自检和 CI 内部浏览器消费者都默认保留隔离运行目录，并在 `results/result.json` 记录最终状态；它们不会自动下载安装浏览器。Windows 启动器测试及构建入口见 [T-LAUNCHER](../SoftwareTesting/launcher/README.md)，其他权威调用、路径和清理边界见[项目完整自检](../SoftwareTesting/project/README.md)与[测试安全](../SoftwareTesting/SAFETY.md)。
