#!/usr/bin/env python3
"""从 automation/history.json 中移除指定的视频 id，使它们能被重新处理。

务必先停掉 bili-mover 服务再运行 —— 运行中的进程内存里那份 history 才是权威，
它下次写盘时会把这里删掉的 id 并集回来。完整说明见 docs/RUNBOOK.md §3。

用法:
    # 推荐：停服务 → 删除 → 起服务，三步连成原子操作
    sudo systemctl stop bili-mover && python3 scripts/prune_history.py <id>... && sudo systemctl start bili-mover

    python3 scripts/prune_history.py --from-file ids.txt    # 每行一个 id
    python3 scripts/prune_history.py --dry-run <id>...      # 只看会删什么
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HISTORY_FILE = Path(__file__).resolve().parent.parent / "automation" / "history.json"


def service_is_running():
    try:
        result = subprocess.run(["systemctl", "is-active", "bili-mover"],
                                capture_output=True, text=True, timeout=10)
        return result.stdout.strip() == "active"
    except Exception:
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("ids", nargs="*", help="要移除的 YouTube 视频 id")
    parser.add_argument("--from-file", help="从文件读取 id（每行一个，支持 # 注释）")
    parser.add_argument("--dry-run", action="store_true", help="只报告，不写入")
    parser.add_argument("--force", action="store_true", help="服务在跑时也强行执行")
    args = parser.parse_args()

    ids = set(args.ids)
    if args.from_file:
        for line in Path(args.from_file).read_text(encoding="utf-8").splitlines():
            line = line.split("#")[0].strip()
            if line:
                ids.add(line)

    if not ids:
        parser.error("没有指定任何 id")

    if service_is_running() and not args.dry_run and not args.force:
        sys.exit("❌ bili-mover 仍在运行，删除会被它写回。\n"
                 "   请先 sudo systemctl stop bili-mover，或加 --force 明确覆盖。")

    history = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    before = len(history)
    present = ids & set(history)
    kept = [x for x in history if x not in ids]

    print(f"待移除 {len(ids)} 个 id，其中 {len(present)} 个存在于 history")
    for missing in sorted(ids - present):
        print(f"  ⚠️ 不在 history 中，跳过: {missing}")

    if args.dry_run:
        print(f"[dry-run] history 将从 {before} 变为 {len(kept)} 条")
        return

    backup = HISTORY_FILE.with_suffix(f".json.bak-prune")
    backup.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")

    fd, tmp = tempfile.mkstemp(dir=str(HISTORY_FILE.parent), prefix=".history-", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(kept, f, ensure_ascii=False, indent=2)
    os.replace(tmp, HISTORY_FILE)

    print(f"✅ history: {before} -> {len(kept)}（移除 {before - len(kept)} 条）")
    print(f"   备份: {backup}")
    print("   记得启动服务，并核对日志里的『已加载历史记录: N 条』是否为新数量")


if __name__ == "__main__":
    main()
