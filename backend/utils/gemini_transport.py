"""在多条出网路径之间轮换，扛住 Gemini 的出口 IP 封锁。

Gemini 会按出口 IP 拒绝请求（400 "User location is not supported"），而哪条出口干净
是会变的：代理最初挂 WARP 正是因为 VPS 原生 IP 被封，但 2026-08-29 实测反了过来——
WARP 的 IPv4 段 0/16 全拒（Gemini 是滥用重灾区，WARP 出口被封得很凶），VPS 原生
IPv4 反而 32/32 全过。

所以这里不押注任何单条路径，而是让重试循环在两条路径间轮换。任何一条还活着，
流水线就能跑；某条被封了下一次尝试自动换另一条，不需要改代码。

两条路径：

  direct-v4  把代理换成 socks5:// 并钉死 IPv4。本地解析 DNS 意味着服务端只收到 IP
             字面量，匹配不上它的 geosite:google 域名规则，于是落到直连出站。
             起决定作用的是本地解析而不是 IP 版本；钉 v4 只为不依赖本地解析器
             恰好把 A 记录排在前面。

  default    保持进程原有的代理环境变量，也就是走代理服务端的正常域名分流（当前挂 WARP）。

实测数据、排查方法和服务端的根治办法见 docs/RUNBOOK.md §5.5。

作用域仅限 Gemini 调用：yt-dlp 用的是自己显式传入的 proxy 参数，PO Token 插件拉起的
无头 Chrome 也在别的阶段，都不受影响。
"""
import os
import socket
from contextlib import contextmanager

from config.settings import GEMINI_PROXY, GEMINI_FORCE_IPV4

_PROXY_ENV_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy")

# 顺序即优先级：第 0 次尝试用第一条。目前 direct-v4 成功率明显更高，所以排前面。
ROUTES = ("direct-v4", "default")


def route_for_attempt(attempt):
    """第 attempt 次尝试该用哪条路径（attempt 从 0 开始）。"""
    if not GEMINI_PROXY:
        return "default"
    return ROUTES[attempt % len(ROUTES)]


@contextmanager
def gemini_network_route(attempt=0):
    route = route_for_attempt(attempt)
    if route == "default":
        yield route
        return

    saved_env = {name: os.environ.get(name) for name in _PROXY_ENV_VARS}
    saved_getaddrinfo = socket.getaddrinfo

    for name in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        os.environ[name] = GEMINI_PROXY
    # ALL_PROXY 留着会让部分栈绕回原来的分流路径
    for name in ("ALL_PROXY", "all_proxy"):
        os.environ.pop(name, None)

    if GEMINI_FORCE_IPV4:
        def ipv4_only_getaddrinfo(host, port, family=0, *args, **kwargs):
            return saved_getaddrinfo(host, port, socket.AF_INET, *args, **kwargs)
        socket.getaddrinfo = ipv4_only_getaddrinfo

    try:
        yield route
    finally:
        socket.getaddrinfo = saved_getaddrinfo
        for name, value in saved_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
