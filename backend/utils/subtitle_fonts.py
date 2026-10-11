"""字幕可选字体：视觉实验室的下拉框、样式校验（automation_store）、ASS 生成共用这一张表。

日文（原文和振假名）和中文（译文）常用的字体不一样，分两组。字体文件都来自 Docker 镜像里的 apt 包（Dockerfile 的字体层），
预览和压制在同一个镜像里用同一批文件渲染。只用标准库：mover 经 automation_store 间接 import 它。
"""
import shutil
import subprocess
from functools import lru_cache

# libass 按 (usWinAscent + usWinDescent) / unitsPerEm 换算字号，不按字面：同样的字号，这个比例是 1.0 的字体
# 比思源黑体（1.448）大 45%。生成 ASS 时字号乘 win_ratio / REFERENCE_WIN_RATIO，同一个字号在哪个字体上字面都一样大；
# 思源黑体的系数是 1，以前的样式渲染结果不变。win_ratio 由 tests/test_subtitle_fonts.py 对着镜像里的字体文件核对。
REFERENCE_WIN_RATIO = 1.448

# family：fontconfig / libass 认的字族名，原样写进 ASS 的 Fontname；package：提供它的 Debian 包。
FONTS = [
    {"family": "Noto Sans CJK JP", "lang": "ja", "label": "源ノ角ゴシック", "note": "思源黑体日文版，默认",
     "package": "fonts-noto-cjk", "win_ratio": 1.448},
    {"family": "Noto Serif CJK JP", "lang": "ja", "label": "源ノ明朝", "note": "思源宋体日文版",
     "package": "fonts-noto-cjk", "win_ratio": 1.437},
    {"family": "BIZ UDGothic", "lang": "ja", "label": "BIZ UDゴシック", "note": "森泽 UD 黑体，笔画清楚",
     "package": "fonts-morisawa-bizud-gothic", "win_ratio": 1.0},
    {"family": "MotoyaLMaru", "lang": "ja", "label": "モトヤLマルベリ", "note": "圆体（丸ゴシック），只有一种字重，粗体是加粗出来的",
     "package": "fonts-motoya-l-maruberi", "win_ratio": 1.0},
    {"family": "Klee One", "lang": "ja", "label": "クレー One", "note": "手写风的教科书体，霞鹜文楷就是照它做的",
     "package": "fonts-klee", "win_ratio": 1.448},
    {"family": "Noto Sans CJK SC", "lang": "zh", "label": "思源黑体", "note": "默认",
     "package": "fonts-noto-cjk", "win_ratio": 1.448},
    {"family": "Noto Serif CJK SC", "lang": "zh", "label": "思源宋体", "note": "",
     "package": "fonts-noto-cjk", "win_ratio": 1.437},
    {"family": "LXGW WenKai", "lang": "zh", "label": "霞鹜文楷", "note": "楷体风格",
     "package": "fonts-lxgw-wenkai", "win_ratio": 1.317},
]

DEFAULT_FONTS = {"ja": "Noto Sans CJK JP", "zh": "Noto Sans CJK SC"}

_BY_FAMILY = {font["family"]: font for font in FONTS}


def find(family):
    return _BY_FAMILY.get(family)


def is_choice(family, lang):
    """能不能给这种语言的字幕选这个字体（只认表里的）。"""
    font = find(family)
    return font is not None and font["lang"] == lang


def size_scale(family):
    """ASS 里的字号 = 界面上的字号 × 这个系数。表外的字体不知道度量，不缩放。"""
    font = find(family)
    return font["win_ratio"] / REFERENCE_WIN_RATIO if font else 1.0


@lru_cache(maxsize=1)
def installed_families():
    """fontconfig 认得的所有字族名（含本地化名）。没有 fc-list 时返回 None，表示不知道。"""
    if not shutil.which("fc-list"):
        return None
    try:
        result = subprocess.run(["fc-list", "--format", "%{family}\n"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return frozenset(name.strip() for line in result.stdout.splitlines() for name in line.split(",") if name.strip())


def is_installed(family):
    """True / False；不知道（没有 fontconfig）时是 None。"""
    families = installed_families()
    return None if families is None else family in families


def catalog():
    """给界面的字体表：每项多一个 installed（None = 不知道）。"""
    return [{**font, "installed": is_installed(font["family"])} for font in FONTS]
