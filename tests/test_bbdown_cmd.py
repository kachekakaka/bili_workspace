
from app.bbdown import build_argv
from app.config import AppConfig


def test_build_argv_uses_isolated_work_dir(tmp_env):
    work = tmp_env.download_dir / ".bili_tmp" / "task"
    cfg = AppConfig(
        download_dir=str(tmp_env.download_dir),
        bbdown_dir=str(tmp_env.bbdown_dir),
        dfn_priority="1080P 高清",
        encoding_priority="hevc,avc",
    )
    argv = build_argv(
        "https://www.bilibili.com/video/BV1qt4y1X7TW", cfg, work_dir=work
    )
    assert argv[argv.index("--work-dir") + 1] == str(work.resolve())
    assert "--file-pattern" in argv and "<videoTitle>" in argv[argv.index("--file-pattern") + 1]
    assert "--ffmpeg-path" in argv
    assert "--dfn-priority" in argv and "1080P 高清" in argv
    assert "--encoding-priority" in argv
