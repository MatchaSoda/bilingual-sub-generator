"""Replay the ASR correction pass on cached videos and compare it with what the cache holds.

For every data/downloads/<title>.asr.json that has a .translated.json next to it, the subtitle
lines are rebuilt with the rule segmenter (the production setting) from the ASR text, the
correction pass runs on them, and every line that the cache or the replay changed is printed:
ASR / cached / replayed. Videos whose rebuilt lines don't match the cached ones are skipped.

Runs in the container (MeCab, a Gemini key). How to read the output: docs/RUNBOOK.md §5.12.

    docker compose run --rm -T setup bash -c \\
        '/app/venv/bin/python3 /app/scripts/replay_asr_correction.py --out /app/data/replay.json'

After changing the checks, re-judge the stored proposals without calling Gemini:

    ... replay_asr_correction.py --from /app/data/replay.json --out /app/data/replay2.json

The title comes from the file name. Pass --descriptions with a JSON {"<file title>": "..."} to
give the model the video descriptions as well, as production does.
"""
import argparse
import collections
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from config.settings import DOWNLOADS_DIR  # noqa: E402
from engines.segment_optimizer import SubtitleSegmentOptimizer  # noqa: E402
from engines.source_corrector import AsrSourceCorrector, JapaneseReader, Reference  # noqa: E402


class RecordingCorrector(AsrSourceCorrector):
    """Keeps the model's raw proposals so --from can re-judge them later."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.proposals = []

    def _request_fixes(self, prompt):
        fixes = super()._request_fixes(prompt)
        self.proposals.extend(fixes)
        return fixes


def replay(args, reader):
    descriptions = json.loads(Path(args.descriptions).read_text(encoding="utf-8")) if args.descriptions else {}
    segmenter = SubtitleSegmentOptimizer(maximum_characters_per_line=25)
    results = {}
    for asr_path in sorted(DOWNLOADS_DIR.glob("*.asr.json")):
        title = asr_path.name[:-len(".asr.json")]
        cache_path = asr_path.with_name(f"{title}.translated.json")
        if not cache_path.exists() or args.match not in title:
            continue
        rebuilt = segmenter.segment(json.loads(asr_path.read_text(encoding="utf-8"))["segments"], source_language="ja")
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        if len(rebuilt) != len(cached) or any(abs(a["start"] - b["start"]) > 0.01 for a, b in zip(rebuilt, cached)):
            print(f"⏭️ lines differ from the cache, skipped: {title}")
            continue
        segments = [{"text": line["text"]} for line in rebuilt]
        corrector = RecordingCorrector(model_name=args.model, reader=reader)
        description = descriptions.get(title, "")
        try:
            report = corrector.correct(segments, "ja", title=title, description=description)
        except Exception as error:
            print(f"❌ {title}: {error}")
            continue
        results[title] = {
            "title": title, "description": description, "original": [line["text"] for line in rebuilt],
            "cached": [line["text"] for line in cached], "new": [segment["text"] for segment in segments],
            "proposals": corrector.proposals, "report": report.to_json(),
        }
        time.sleep(2)
    return results


def rejudge(args, reader):
    results = json.loads(Path(args.previous).read_text(encoding="utf-8"))
    for entry in results.values():
        segments = [{"text": text} for text in entry["original"]]
        corrector = AsrSourceCorrector(model_name=entry["report"]["model"], reader=reader)
        entry["report"] = corrector.apply_fixes(
            segments, entry["proposals"], Reference.from_page(entry["title"], entry["description"])).to_json()
        entry["new"] = [segment["text"] for segment in segments]
    return results


def print_comparison(results):
    totals = collections.Counter()
    reasons = collections.Counter()
    for entry in results.values():
        rows = [(index, asr, cached, new) for index, (asr, cached, new)
                in enumerate(zip(entry["original"], entry["cached"], entry["new"])) if cached != asr or new != asr]
        totals.update(videos=1, lines=len(entry["original"]),
                      cached_changed=sum(cached != asr for _, asr, cached, _ in rows),
                      replay_changed=sum(new != asr for _, asr, _, new in rows),
                      same_change=sum(cached == new != asr for _, asr, cached, new in rows))
        reasons.update(item["reason"] for item in entry["report"]["rejected"])
        if rows:
            print(f"\n## {entry['title']}")
            for index, asr, cached, new in rows:
                print(f"[{index}] ASR    {asr}\n      cached {'=' if cached == asr else cached}\n"
                      f"      replay {'=' if new == asr else new}")
    print(f"\n{dict(totals)}\nrejected by reason: {dict(reasons)}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", required=True, help="where to save the results (JSON)")
    parser.add_argument("--from", dest="previous", help="re-judge the proposals in an earlier --out, no Gemini calls")
    parser.add_argument("--model", help="correction model (default: source_corrector.CORRECTION_MODEL)")
    parser.add_argument("--match", default="", help="only titles containing this text")
    parser.add_argument("--descriptions", help='JSON {"<file title>": "<description>"}')
    args = parser.parse_args()

    reader = JapaneseReader()
    results = rejudge(args, reader) if args.previous else replay(args, reader)
    Path(args.out).write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print_comparison(results)


if __name__ == "__main__":
    main()
