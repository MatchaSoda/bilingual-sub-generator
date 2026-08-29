"""让 Gemini 的 REST 调用绕开代理服务端的域名分流。

Gemini 会拒绝我们 WARP 出口的请求（返回 400 "User location is not supported"），
但接受 VPS 自己的 IPv4 出口。走 SOCKS 且**在本地解析** DNS，服务端就只看到一个 IP
字面量、匹配不上它的域名规则，于是落到直连出站——正好是能用的那个出口。

决定性的是本地解析这一步，不是 IP 版本；额外钉死 IPv4 只是为了不依赖本地解析器
恰好把 A 记录排在前面。完整测量数据和取舍见 docs/RUNBOOK.md §5.5。

只在 Gemini 调用期间生效：yt-dlp 用的是自己显式传入的 proxy 参数，PO Token 插件拉起的
无头 Chrome 也在别的阶段，都不受影响。
"""
import os
import socket
from contextlib import contextmanager

from config.settings import GEMINI_PROXY, GEMINI_FORCE_IPV4

_PROXY_ENV_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy")


@contextmanager
def gemini_network_route():
    if not GEMINI_PROXY:
        yield
        return

    saved_env = {name: os.environ.get(name) for name in _PROXY_ENV_VARS}
    saved_getaddrinfo = socket.getaddrinfo

    for name in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        os.environ[name] = GEMINI_PROXY
    # requests 对 https:// 优先用 HTTPS_PROXY，但 ALL_PROXY 留着会让部分栈走回原路由
    for name in ("ALL_PROXY", "all_proxy"):
        os.environ.pop(name, None)

    if GEMINI_FORCE_IPV4:
        def ipv4_only_getaddrinfo(host, port, family=0, *args, **kwargs):
            return saved_getaddrinfo(host, port, socket.AF_INET, *args, **kwargs)
        socket.getaddrinfo = ipv4_only_getaddrinfo

    try:
        yield
    finally:
        socket.getaddrinfo = saved_getaddrinfo
        for name, value in saved_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
