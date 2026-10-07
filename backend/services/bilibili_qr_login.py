"""B 站扫码登录的独立进程（services/bilibili_account.py 启动它）。

不能在 Web 进程里直接调 stream_gears：login_by_qrcode 轮询期间一直攥着 GIL，整个 Python 进程的其他线程
全部停住（10-07 实测：后台线程等扫码时，主线程 30 秒一次都没跑到），Web 服务会跟着卡死到二维码过期。

输出协议：每条结果一行，带固定前缀，别的输出（biliup 自己的日志）一律忽略。
  @@QR {get_qrcode 的返回}
  @@LOGIN {"info": 登录信息 JSON 字符串}
  @@ERROR {"message": ...}
"""
import json
import sys


def emit(tag, payload):
    print(f"@@{tag} {json.dumps(payload, ensure_ascii=False)}", flush=True)


def main():
    try:
        import stream_gears
    except ImportError as e:
        emit("ERROR", {"message": f"没有装 biliup（stream_gears）: {e}"})
        return 1
    try:
        raw = stream_gears.get_qrcode(None)
        emit("QR", json.loads(raw))
    except Exception as e:  # noqa: BLE001
        emit("ERROR", {"message": f"获取二维码失败: {e}"})
        return 1
    try:
        emit("LOGIN", {"info": stream_gears.login_by_qrcode(raw, None)})
    except Exception as e:  # noqa: BLE001 过期、网络都走这里
        emit("ERROR", {"message": str(e)})
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
