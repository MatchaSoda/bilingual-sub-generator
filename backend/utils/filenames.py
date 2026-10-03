"""文件名按字节截断。

Linux 文件系统限制的是单个文件名 255 **字节**，不是字符；日文 / 中文在 UTF-8 下
每字 3 字节，85 个字左右的标题就到顶了。见 docs/RUNBOOK.md §5.7。
"""

# 给标题留的字节预算。剩下的 55 字节留给流水线追加的后缀（最长是 yt-dlp 的
# `.f399.mp4.part` / `.part-Frag123.part`、`.translated.json`、`_bilingual.mp4`）
# 以及 yt-dlp 在截断之后才做的净化（`/` → `⧸` 这类全角替换每个多 2 字节）。
TITLE_MAX_BYTES = 200


def truncate_utf8(name, max_bytes=TITLE_MAX_BYTES):
    """截到不超过 max_bytes 字节，不会切开多字节字符。"""
    encoded = name.encode("utf-8")
    if len(encoded) <= max_bytes:
        return name
    return encoded[:max_bytes].decode("utf-8", "ignore").rstrip()
