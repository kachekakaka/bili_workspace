# 辅助脚本

仓库根目录只保留两个 Windows 用户入口：

```text
start.bat   启动应用
verify.bat  部署自检；严格 T-PROJECT full 还要求 Node.js 和既有兼容浏览器
```

其余脚本按用途收纳：

```text
scripts/windows/bootstrap-runtime.bat   启动 PowerShell 运行包准备器
scripts/windows/bootstrap-portable.ps1  校验并解压仓库内置 Windows 运行包
scripts/windows/prepare-runtime.bat     为正常启动准备运行时并同步实际本地配置
scripts/windows/new-test-run.ps1        创建并记账仓库外 T-PROJECT 运行目录
scripts/windows/configure-network.bat   命令行修改监听地址和端口
scripts/windows/bilibili-login.bat      BBDown 命令行登录备用入口
scripts/dev/verify-source.sh             Linux/macOS 源码校验入口
scripts/dev/run-playwright-phase.sh      CI 内部 T-PROJECT 浏览器阶段消费者
```

Windows 正常使用不需要直接运行内部准备脚本；`verify.bat` 不调用正常启动的配置准备链，而是在带所有权标记的仓库外 run-id 中解压运行时和生成隔离配置。网络和 Bilibili 登录优先使用网站设置页；命令行脚本只作为备用。Linux/macOS 开发环境使用：

```bash
python -m pip install -r requirements/dev.lock
sh scripts/dev/verify-source.sh
```

两个规范验证入口和 CI 内部浏览器消费者都默认保留隔离运行目录，并在 `results/result.json` 记录最终状态。Windows 非严格部署自检跳过 Node 或 Playwright 时记录 `inconclusive`；严格 full 不会自动下载安装浏览器，缺少既有浏览器时记录 `blocked`。权威调用、路径和清理边界见[项目完整自检](../SoftwareTesting/project/README.md)与[测试安全](../SoftwareTesting/SAFETY.md)。
