# 辅助脚本

Windows 日常用户入口只有仓库跟踪的 `dist/bili-workspace-launcher-0.7.0.exe`；根目录不再保留启动或部署自检批处理。

```text
scripts/windows/build-launcher.bat   使用根目录唯一 .venv 构建并自检规范 EXE
scripts/windows/new-test-run.ps1     创建并记账仓库外 T-PROJECT 运行目录
scripts/dev/verify-source.sh         Linux/macOS/CI 源码完整自检入口
scripts/dev/run-playwright-phase.sh  CI 内部 T-PROJECT 浏览器阶段消费者
```

`build-launcher.bat` 是开发者构建入口，不是第二套日常启动链。网络、局域网服务器模式和 Bilibili 登录由启动器及 Web 界面管理。Linux/macOS 开发环境使用：

```bash
python -m pip install -r requirements/dev.lock
sh scripts/dev/verify-source.sh
```

源码完整自检和 CI 内部浏览器消费者都默认保留隔离运行目录，并在 `results/result.json` 记录最终状态；它们不会自动下载安装浏览器。Windows 启动器测试及构建入口见 [T-LAUNCHER](../SoftwareTesting/launcher/README.md)，其他权威调用、路径和清理边界见[项目完整自检](../SoftwareTesting/project/README.md)与[测试安全](../SoftwareTesting/SAFETY.md)。
