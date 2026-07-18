# Windows 外部工具目录

GitHub 源码仓库**不提交** `BBDown.exe`、`ffmpeg.exe` 和离线 wheelhouse：

- `ffmpeg.exe` 超过 GitHub 普通 Git 对单文件的限制；
- 第三方二进制不应混入源码提交历史；
- 登录后生成的 `BBDown.data` 含账号会话，必须始终保持未跟踪状态。

Windows 用户可保留之前完整包中的工具目录；这些文件被 Git 忽略，后续拉取源码不会覆盖。全新克隆时，`setup.bat` 会运行 `tools/bootstrap_windows_runtime.py`，从 GitHub Release 或仓库根目录的本地运行包安装并校验：

```text
BBDown_portable/BBDown.exe
BBDown_portable/ffmpeg/bin/ffmpeg.exe
wheelhouse/*.whl
```

默认运行包名称：

```text
bili_workspace_v0.5.4_windows_runtime.zip
```

整个运行包和内部每个文件均使用 SHA-256 校验，并拒绝路径穿越、符号链接、重复路径和清单外文件。

V0.5.x Windows 完整包中已验证的文件哈希为：

```text
BBDown.exe
SHA-256 eb8b985af07c4757fa695204283208aee879bf79f6462a1d161e3a55b5a19cb1

ffmpeg.exe
SHA-256 a25942892c8e5180c2998f9936f56e914cece03708b93e8d54f38d23304dcf8c
```

工具安装后可运行 `verify.bat` 做真实 EXE 冒烟测试。发布清单只用于完整包逐文件校验；源码克隆即使没有发布清单，只要工具存在也会实际启动 BBDown 和 FFmpeg。


设置 `BILI_SKIP_RUNTIME_DOWNLOAD=1` 可以只创建网站环境。缺少工具时 V0.5.4 网站和媒体库仍可启动，但下载、混流、扫码登录和兼容转码会显示工具未就绪。
