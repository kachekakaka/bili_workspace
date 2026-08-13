# Qt / PySide6 对应源码与替换、重新链接说明

本说明适用于使用 Qt/PySide6 开源许可构建的 `bili_workspace` Windows amd64
启动器，不构成法律意见。构建者若使用 Qt 商业许可，应保留与该候选对应的许可
证据，并按其条款处理；不得把商业许可假设写进开源候选。

## 对应源码

候选固定使用 Qt for Python / PySide6 `6.11.1`。官方对应源码入口为：

- Qt for Python（PySide6 与 Shiboken6）：
  `https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.11.1-src/pyside-setup-everywhere-src-6.11.1.tar.xz`
- 本候选使用的 Qt Core、Gui、Widgets、Network 与 Windows 平台插件来自
  `qtbase`：
  `https://download.qt.io/official_releases/qt/6.11/6.11.1/submodules/qtbase-everywhere-src-6.11.1.tar.xz`

构建器会原样收集 wheel 实际提供的许可证文件；由于 `6.11.1` wheel 的文件清单
只列出 Qt 商业许可引用，构建器还会从上述 Qt for Python 官方源码仓库的固定
`v6.11.1` 标签下载 LGPLv3、GPLv3 与 Qt GPL exception 全文，逐项校验大小和
SHA-256 后保存到本目录，并由 `manifest.json` 记录。正式对外提供候选时，分发者
仍须按所选许可保留对应源码或提供有效的取得方式；仅列出网址不自动证明全部
义务已满足。

FFmpeg 固定使用官方签名的 `7.1.1` 源码归档：
`https://ffmpeg.org/releases/ffmpeg-7.1.1.tar.xz`。构建器在固定 Debian 快照和
固定 Linux/amd64 容器中交叉编译 Windows amd64 `ffmpeg.exe`，不启用 GPL、
version3、nonfree 或外部编解码库，许可模式为 LGPL-2.1-or-later。完整源码归档、
签名、官方发布公钥、Dockerfile、构建脚本、配置、工具链包清单、PE 导入清单与
许可证全文都随候选保存在 `THIRD_PARTY_SOURCES` 或 `windows-tools/LICENSES`；
机器生成的身份记录位于 `THIRD_PARTY_LICENSES/FFmpeg.SOURCE.json`。任一来源、
配方、实际二进制、许可模式或资源清单身份不一致时，构建失败关闭。

## 使用修改后的 Qt/PySide6 重新构建

1. 取得候选随附的应用源码或同一 `build_id` 对应仓库源码，并安装 Windows
   amd64 Python 3.11。
2. 按 Qt 官方说明构建修改后的 Qt `6.11.1` 与 Qt for Python `6.11.1`，或准备
   ABI 兼容、包含所需 Qt DLL/插件的修改版 PySide6 wheel。
3. 在独立构建环境中安装修改版 PySide6/Shiboken6，以及
   `launcher/requirements-dev.txt` 中其余固定依赖。不要再安装官方 PySide6
   覆盖修改版。
4. 使用 `tools/build_launcher.py` 和
   `launcher/bili-workspace-launcher.spec` 重建。构建器会重新收集实际环境中的
   许可证文件、重算资源清单与 `build_id`；修改后的结果不会冒充原候选身份。
5. 执行构建自检和 Windows 产品冒烟，确认修改后的 DLL 能被单文件展开并加载。

项目不附加禁止为调试、替换或重新链接 LGPL 组件而进行反向工程的条款，也不以
签名、DRM 或设备锁阻止用户运行按上述方式重新构建的程序。
