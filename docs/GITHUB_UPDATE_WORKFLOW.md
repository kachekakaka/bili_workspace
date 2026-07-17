# GitHub 更新工作流

本仓库采用运行配置与源码分离的更新方式：

- Git 仅跟踪 `*.default` 配置模板；
- 首次启动自动生成同名运行配置；
- 升级时只补充缺失字段，不覆盖已有值；
- Windows 使用 `update_from_github.bat` 拉取代码、Git LFS 对象并执行自检；
- Docker 将 `/data/config`、`/data/media`、`/data/cache`、`/data/tmp` 映射到 QNAP 宿主机目录；
- 监听地址与端口可通过 `config/server.json` 或环境变量配置；手机访问可绑定 `0.0.0.0` 并使用电脑/NAS 的局域网 IP；
- 非回环监听必须使用网站认证，公网部署应使用 HTTPS 反向代理。

大型 Windows 工具与离线依赖由 Git LFS 管理；`.venv` 不进入仓库，因为其中包含机器、目录、操作系统和 Python ABI 相关内容。目标机器通过固定依赖和离线 wheelhouse 重建虚拟环境。
