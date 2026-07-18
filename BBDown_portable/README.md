# Windows 外部工具目录

本目录是 Windows 便携运行时的解压目标。Git 只跟踪本说明、许可证、备用 `run.bat` 和空目录占位；实际可执行文件由仓库中的集成运行包生成：

```text
vendor/windows/media-runtime.pack
vendor/windows/runtime-manifest.json
```

运行 `start.bat`、`verify.bat` 或内部 `scripts/windows/prepare-runtime.bat` 时，会先校验运行包 SHA-256 和包内逐文件清单，再安全解压：

```text
BBDown_portable/BBDown.exe
BBDown_portable/ffmpeg/bin/ffmpeg.exe
```

该过程不访问 PyPI 或 GitHub Release，也不要求系统预装 BBDown、FFmpeg 或 Python。解压出的 EXE 被 `.gitignore` 排除，不会污染源码提交。

Bilibili 登录后生成的 `BBDown.data` 含账号会话，必须始终保持未跟踪状态并加密备份。推荐在网站“账号”页面扫码登录；命令行备用入口为：

```text
scripts/windows/bilibili-login.bat
```

`BBDown_portable/run.bat` 仅用于维护人员直接调用 BBDown，例如：

```bat
BBDown_portable\run.bat --help
```

完整运行时和源码边界见 [`vendor/windows/README.md`](../vendor/windows/README.md) 与 [`docs/源文件与恢复清单.md`](../docs/源文件与恢复清单.md)。
