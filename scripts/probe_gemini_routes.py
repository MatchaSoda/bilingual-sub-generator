#!/usr/bin/env python3
"""Measure Gemini reachability per egress route, using the pipeline's own transport.

    venv/bin/python3 scripts/probe_gemini_routes.py [calls_per_route]

Prints "<route>: ok/n" for each entry in gemini_transport.ROUTES plus the first error.
A 400 "User location is not supported" means that egress IP is geo-blocked; see
docs/RUNBOOK.md §5.5. Run it whenever the pipeline logs a burst of
"Attempt N failed (route=...)" to see which side is dead right now.
"""
import os
import sys
import time
import warnings

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))

import google.generativeai as genai  # noqa: E402
from config.keys import key_manager  # noqa: E402
from config.settings import MODEL_NAME  # noqa: E402
from utils.gemini_transport import ROUTES, gemini_network_route, route_for_attempt  # noqa: E402


def one_call(attempt):
    genai.configure(api_key=key_manager.get_next_available_api_key(), transport="rest")
    with gemini_network_route(attempt):
        response = genai.GenerativeModel(MODEL_NAME).generate_content(
            "Reply with the single word OK.", request_options={"timeout": 45, "retry": None}
        )
    return response.text.strip()


def main():
    calls_per_route = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    for attempt in range(len(ROUTES)):
        route = route_for_attempt(attempt)
        successes, first_error = 0, ""
        for _ in range(calls_per_route):
            try:
                one_call(attempt)
                successes += 1
                print(".", end="", flush=True)
            except Exception as error:  # noqa: BLE001 - we want the raw text
                first_error = first_error or str(error)[:110]
                print("x", end="", flush=True)
            time.sleep(1)
        print(f"\n{route}: {successes}/{calls_per_route}  {first_error}")


if __name__ == "__main__":
    main()
