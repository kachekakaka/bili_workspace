# 第三方组件说明

## BBDown

- 项目：`nilaoda/BBDown`
- Windows 文件：`BBDown_portable/BBDown.exe`
- Docker 构建：固定下载上游 `v1.6.3` 的 Linux x64 或 Linux arm64 发布文件
- 许可证：MIT；Windows 包全文见 `BBDown_portable/BBDown.LICENSE.txt`
- 上游仓库：`https://github.com/nilaoda/BBDown`

BBDown 官方仓库已经归档。V0.5 固定使用 v1.6.3，并在 Windows 发布包中校验现有二进制哈希；Docker 构建阶段会执行 `BBDown --help` 冒烟测试。

## FFmpeg / FFprobe

- Windows 文件：`BBDown_portable/ffmpeg/bin/ffmpeg.exe`
- Windows 原始目录标识：`ffmpeg-n8.1-latest-win64-gpl-8.1`
- Windows 许可证文本：`BBDown_portable/ffmpeg/LICENSE.txt`
- Docker：使用 Debian Bookworm 软件源安装 `ffmpeg`，同时提供 `ffprobe`
- 上游网站：`https://ffmpeg.org/`

Windows 随包二进制不做修改，其哈希记录在 `BBDown_portable/checksums.sha256` 和发布清单中。

## QRCode.js

- 用途：在浏览器端渲染 Bilibili 一次性扫码登录二维码
- 文件：`web/assets/qrcode.min.js`
- 项目：`davidshimjs/qrcodejs`
- 许可证：MIT；全文见 `LICENSES/QRCodeJS.LICENSE.txt`

## Python 依赖

固定运行依赖见 `requirements/runtime.lock`；Windows 自检与开发依赖见 `requirements/dev.lock`。各组件继续受其各自许可证约束。
