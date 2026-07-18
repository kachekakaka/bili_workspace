# Windows 外部工具目录

GitHub 源码仓库**不提交** `BBDown.exe`、`ffmpeg.exe` 和离线 wheelhouse：

- `ffmpeg.exe` 超过 GitHub 普通 Git 对单文件的限制；
- 第三方二进制不应混入源码提交历史；
- 登录后生成的 `BBDown.data` 含账号会话，必须始终保持未跟踪状态。

Windows 用户可保留之前完整包中的工具目录；这些文件被 Git 忽略，后续拉取源码不会覆盖。需要从源码目录运行时，请将工具放到以下位置：

```text
BBDown_portable/BBDown.exe
BBDown_portable/ffmpeg/bin/ffmpeg.exe
```

V0.5.x Windows 完整包中已验证的文件哈希为：

```text
BBDown.exe
SHA-256 eb8b985af07c4757fa695204283208aee879bf79f6462a1d161e3a55b5a19cb1

ffmpeg.exe
SHA-256 a25942892c8e5180c2998f9936f56e914cece03708b93e8d54f38d23304dcf8c
```

放入工具后可运行 `verify.bat` 做完整冒烟测试。源码目录缺少发布清单或二进制时，`verify.bat` 会自动切换为源码自检模式，只运行 Python、Ruff、测试和前端语法检查。


缺少工具时 V0.5.3 网站和媒体库仍可启动，但下载、混流、扫码登录和兼容转码会显示工具未就绪。
