# 辅助脚本

仓库根目录只保留 Windows 用户最常用的三个入口：

```text
start.bat   启动应用
update.bat  快进更新 main 并执行完整自检
verify.bat  校验源码、便携 Python、BBDown、FFmpeg 和前端脚本
```

其余脚本按用途收纳：

```text
scripts/windows/bootstrap-runtime.bat   启动 PowerShell 运行包准备器
scripts/windows/bootstrap-portable.ps1  校验并解压仓库内置 Windows 运行包
scripts/windows/prepare-runtime.bat     准备运行时并同步配置
scripts/windows/configure-network.bat   命令行修改监听地址和端口
scripts/windows/bilibili-login.bat      BBDown 命令行登录备用入口
scripts/dev/verify-source.sh             Linux/macOS 源码校验入口
```

Windows 正常使用不需要直接运行内部准备脚本。网络和 Bilibili 登录优先使用网站设置页；命令行脚本只作为备用。Linux/macOS 开发环境使用：

```bash
python -m pip install -r requirements/dev.lock
sh scripts/dev/verify-source.sh
```
