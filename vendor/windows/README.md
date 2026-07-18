# Windows 集成运行时

V0.5.6 将 Windows x64 的运行环境以两个普通 Git 文件放进仓库：

```text
python-runtime.pack  Python 3.13.14 + 锁定 Python 依赖
media-runtime.pack   BBDown 1.6.3 + FFmpeg
runtime-manifest.json
```

文件由 `.github/workflows/build-integrated-runtime.yml` 在 GitHub Windows Runner 中从固定官方来源构建，构建前校验上游 SHA-256，构建后执行 Python 导入、BBDown 和 FFmpeg 冒烟测试，并把最终包哈希写入清单。

两个 `.pack` 都是 ZIP 格式但使用独立扩展名，避免与用户下载 ZIP 混淆。每个文件均小于 GitHub 普通 Git 的 100 MiB 单文件限制，因此不要求 Git LFS。

用户执行 `git pull` 或全新 `git clone` 后，直接双击 `start.bat`。它通过 `scripts/windows/prepare-runtime.bat` 和 `scripts/windows/bootstrap-runtime.bat` 在本地安全解压到被 Git 忽略的 `.runtime/` 和 `BBDown_portable/`，不访问 PyPI、不下载 GitHub Release，也不要求系统预装 Python。
