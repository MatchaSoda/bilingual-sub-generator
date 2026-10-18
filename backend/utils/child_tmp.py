"""给 yt-dlp / entry_cli 子进程一个独立的临时目录，进程结束后整个删掉。

PO Token 插件（yt-dlp-getpot-wpc → nodriver）每次运行都在 TMPDIR 下 mkdtemp 出 Chromium
profile（uc_*，用过的约 55 MB）和 org.chromium.Chromium.* 临时文件，自己只在正常退出时清理一部分，
被 OOM 杀掉时一个都不清。母进程按目录兜底删除，和子进程怎么死的无关。见 docs/RUNBOOK.md §5.15。
只用标准库：mover 直接 import。
"""
import contextlib
import os
import shutil
import tempfile


@contextlib.contextmanager
def child_tmp_env(base_env=None, prefix="bsg-child-"):
    """yield 一份 TMPDIR/TMP/TEMP 指向新建临时目录的环境变量；退出 with 时删掉这个目录。"""
    path = tempfile.mkdtemp(prefix=prefix)
    env = dict(os.environ if base_env is None else base_env)
    env["TMPDIR"] = env["TMP"] = env["TEMP"] = path
    try:
        yield env
    finally:
        shutil.rmtree(path, ignore_errors=True)


def sweep_stale_browser_tmp(tmp_root=None, max_age_seconds=6 * 3600, now=None):
    """删掉 tmp_root 下超过 max_age_seconds 没动过的 nodriver / Chromium 临时目录，返回 (个数, 字节数)。

    只认 uc_* 和 org.chromium.Chromium.* 这两种名字，别的一概不碰。child_tmp_env 之前留下的、
    以及不经过它的调用方漏下的，都靠这个收尾。
    """
    import time

    tmp_root = tmp_root or tempfile.gettempdir()
    now = time.time() if now is None else now
    removed, freed = 0, 0
    try:
        entries = list(os.scandir(tmp_root))
    except OSError:
        return 0, 0
    for entry in entries:
        if not (entry.name.startswith("uc_") or entry.name.startswith("org.chromium.Chromium.")):
            continue
        try:
            if entry.is_symlink() or not entry.is_dir(follow_symlinks=False):
                continue
            if now - entry.stat(follow_symlinks=False).st_mtime < max_age_seconds:
                continue
            size = _tree_size(entry.path)
            shutil.rmtree(entry.path)
            removed += 1
            freed += size
        except OSError:
            continue
    return removed, freed


def _tree_size(path):
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.lstat(os.path.join(root, name)).st_size
            except OSError:
                pass
    return total
