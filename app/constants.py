from __future__ import annotations

APP_VERSION = "0.5.6"

WBI_KEY_CACHE_SECONDS = 10 * 60
SEARCH_PAGE_CACHE_SECONDS = 3 * 60

MAX_BATCH_ITEMS = 100
MAX_PENDING_TASKS = 100
MAX_TASK_HISTORY = 100
MAX_INPUT_LENGTH = 2048
MAX_REQUEST_BODY_BYTES = 256 * 1024
MAX_LOG_TAIL_CHARS = 12_000
MAX_LOG_FILE_BYTES = 5 * 1024 * 1024
MAX_LOG_API_CHARS = 250_000
MAX_INFO_OUTPUT_CHARS = 1_000_000

TERMINAL_STATUSES = frozenset({"success", "skipped", "failed", "cancelled"})
MEDIA_EXTENSIONS = frozenset(
    {
        ".mp4",
        ".mkv",
        ".flv",
        ".webm",
        ".mov",
        ".ts",
        ".m4a",
        ".mp3",
        ".aac",
        ".wav",
        ".flac",
        ".ogg",
    }
)
