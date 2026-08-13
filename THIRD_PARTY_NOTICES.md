# 第三方组件说明

## BBDown

- 项目：`nilaoda/BBDown`
- Windows 文件：由 `dist/bili-workspace-launcher-0.7.0.exe` 内置并展开到 EXE 同级已校验资源目录
- Docker 构建：固定下载上游 `v1.6.3` 的 Linux x64 或 Linux arm64 发布文件
- 许可证：MIT；Windows 候选内随附许可证全文
- 上游仓库：`https://github.com/nilaoda/BBDown`

BBDown 官方仓库已经归档。当前 Windows 启动器固定使用 v1.6.3，构建与运行时均校验固定包和展开二进制哈希；身份由启动器资源清单和 `launcher/current-build.json` 承接。Docker 构建阶段会执行 `BBDown --help` 冒烟测试。

## FFmpeg / FFprobe

- Windows 文件：由当前 EXE 内置并展开到 `resources/<build_id>/windows-tools/ffmpeg/bin/ffmpeg.exe`
- Windows 构建来源：FFmpeg 7.1.1 官方签名源码，在固定 `linux/amd64` 容器中交叉构建 Windows amd64 二进制
- Windows 许可证：LGPL-2.1-or-later；完整源码、签名、公钥、配方、工具链与许可证随候选资源提供
- Docker：使用 Debian Bookworm 软件源安装 `ffmpeg`，同时提供 `ffprobe`
- 上游网站：`https://ffmpeg.org/`

Windows 构建器验证官方源码归档、分离签名和发布密钥指纹，并拒绝 GPL、nonfree、version3 或未登记外部库配置。二进制、PE 导入、转码冒烟和资源摘要由启动器构建门禁共同核对。

## QRCode.js

- 用途：在浏览器端渲染 Bilibili 一次性扫码登录二维码
- 文件：`web/assets/qrcode.min.js`
- 项目：`davidshimjs/qrcodejs`
- 许可证：MIT；全文见 `LICENSES/QRCodeJS.LICENSE.txt`

## Python 依赖

固定运行依赖见 `requirements/runtime.lock`；统一开发依赖见 `requirements/dev.lock`，Windows 启动器附加依赖见 `launcher/requirements*.txt`。各组件继续受其各自许可证约束。
