# Windows 启动器只导出 amd64 Docker 镜像

Windows 启动器的 Docker 构建导出入口固定生成单平台 `linux/amd64` 镜像 tar，不提供 arm64 选择，也不生成混合多平台包，以匹配当前 Intel QNAP 目标并保持导入与验证流程单一。该限制只定义启动器的用户侧交付入口，不要求删除 Dockerfile 或 CI 已有的 arm64 可构建性；未来若启动器需要服务其他架构，应重新确认目标设备、导出格式与验证义务。
