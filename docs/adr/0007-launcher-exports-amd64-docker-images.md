# Windows 启动器只导出 linux/amd64

Windows 启动器的 Docker 导出协议只生成适用于 `linux/amd64` 的 Docker 导出三件套，以匹配当前 Intel QNAP 目标并保持用户侧导入与验证协议单一。一般 Docker 构建仍可验证 arm64；为启动器增加其他架构将同时扩大目标设备、产物命名和验证义务，因此需要重新决策。
