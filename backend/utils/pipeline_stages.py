"""从 entry_cli.py 的输出行推断流水线走到了哪一步，给界面画分阶段进度。

Web 任务（services/job_manager.py）和自动搬运（automation/mover.py）读的是同一份 CLI 输出，
所以两边共用这张表。只认 entry_cli / engines 里固定打印的几行，没匹配到就保持上一个阶段。
"""

# (界面上的阶段 key, 中文名)，顺序就是流水线的顺序；upload 只有投稿任务才有
STAGES = (
    ("download", "下载"),
    ("transcribe", "转写"),
    ("translate", "翻译"),
    ("encode", "压制"),
    ("upload", "投稿"),
)

_MARKERS = (
    ("Starting process for", "download"),
    ("Loading Whisper model", "transcribe"),
    ("Loading cached ASR", "transcribe"),
    ("Transcribing:", "transcribe"),
    ("Segmentation mode", "translate"),
    ("Requesting Gemini", "translate"),
    ("Loading cached translations", "translate"),
    ("Executing FFmpeg", "encode"),
)


def detect_stage(line):
    """这一行标志着进入哪个阶段；不是阶段标志就返回 None。"""
    for marker, stage in _MARKERS:
        if marker in line:
            return stage
    return None
