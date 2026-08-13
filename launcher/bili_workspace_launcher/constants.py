"""启动器稳定常量与内部协议名。"""

from __future__ import annotations

APP_NAME = "bili_workspace"
EXECUTABLE_BASENAME = "bili-workspace-launcher-0.7.0.exe"
DEFAULT_BACKEND_HOST = "127.0.0.1"
DEFAULT_BACKEND_PORT = 3398
DOCKER_PLATFORM = "linux/amd64"

OWNER_LABEL_KEY = "io.biliworkspace.launcher.owner"
OWNER_LABEL_VALUE = "bili-workspace-launcher"
JOB_LABEL_KEY = "io.biliworkspace.launcher.job"
BUILD_LABEL_KEY = "io.biliworkspace.launcher.build-id"

BACKEND_START_TIMEOUT_SECONDS = 30.0
BACKEND_STOP_TIMEOUT_SECONDS = 45.0
BACKEND_READY_HEALTH_INTERVAL_SECONDS = 10.0
MAX_TRACKED_EXE_BYTES = 100 * 1024 * 1024
