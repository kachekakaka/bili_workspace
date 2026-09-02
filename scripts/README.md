# 辅助脚本

Windows 日常用户入口只有仓库跟踪的 `dist/bili-workspace-launcher-0.7.0.exe`；根目录不再保留启动或部署自检批处理。

```text
scripts/windows/validate-launcher-candidate.bat  构建、自检、运行并默认清理临时候选
scripts/windows/build-launcher.bat              从干净已提交 HEAD 晋升 Windows 打包快照
scripts/windows/new-test-run.ps1     创建并记录 T-DOCKER 手工验证的仓库外运行目录
scripts/dev/verify-source.sh         Linux/macOS/CI 源码完整自检入口
scripts/dev/run-playwright-phase.sh  CI 内部 T-PROJECT 浏览器阶段消费者
```

两个 Windows 脚本共用 `tools.build_launcher`，不是两套打包实现。候选脚本只接受可选的 `--keep-candidate`，不会写入 `dist`、`launcher/current-build.json` 或上传产物；正式脚本不接受输出路径透传，只能在干净、已提交的 `HEAD` 上更新成对快照。两者都不会 commit、push 或发布。网络、局域网服务器模式和 Bilibili 登录由启动器及 Web 界面管理。Linux/macOS 开发环境使用：

```bash
python -m pip install -r requirements/dev.lock
sh scripts/dev/verify-source.sh
```

PowerShell 帮助器的 `Create` 和 `Record` 保留既有调用形状，但只接受 `-TestId T-DOCKER`，用于 Docker 手工验证的最小交接；它不读取或迁移旧运行记录。T-PROJECT 使用专用 Python 帮助器创建、校验和精确清理临时 run。

源码完整自检在输出结果和诊断后清理自己的隔离 run；CI 浏览器消费者把 run 保留到 Artifact 上传完成。两者都不会自动安装或下载浏览器。Windows 启动器测试及构建入口见 [T-LAUNCHER](../SoftwareTesting/launcher/README.md)，其他权威调用、路径和清理边界见[项目完整自检](../SoftwareTesting/project/README.md)与[测试安全](../SoftwareTesting/SAFETY.md)。
