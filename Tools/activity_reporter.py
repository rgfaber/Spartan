#!/usr/bin/env python3
"""activity_reporter -- publish what this entity is DOING, not just what it says.

Spartan narrates itself to stdout: the action it takes, the thought it has, the
model call it makes, the alert it receives. Between two messages an agent may
think for minutes, and to anything watching from outside it looks dead. This
tails that narration and reports it to the entity's hecate-spartan node
(POST /v1/activity), which records it and publishes it to the mesh. A spectator
can then watch the society WORK, not just overhear it talk.

It reads the entity's own identity (the same Ed25519 key + UCAN the bridge
uses), so an agent reports as itself. Nothing else may report on its behalf.

    python3 Tools/activity_reporter.py --config <state.json> --log <file>
"""
import argparse
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import requests
from macula_radio import auth_headers, refresh_ucan

# What a line of Spartan's narration means, in the order we test it. First match
# wins, so put the specific patterns above the general ones.
PATTERNS = [
    (re.compile(r"ACTION:\s*(?P<what>[\w_]+)"), "action"),
    (re.compile(r"\[Message From:\s*(?P<what>[^\]]+)\]"), "alert"),
    (re.compile(r"Calling\s+(?P<what>[\w/.\-]+)"), "model"),
    (re.compile(r"API:\s*(?P<what>in=[\d,]+.*)"), "model"),
    (re.compile(r"CMO complete:\s*(?P<what>.+)"), "cycle"),
    (re.compile(r"\[E:(?P<e>\d+)\]\s*(?P<what>.{4,})"), "thought"),
]

# A cognition cycle is chatty. Cap the reporting rate so the page shows a pulse,
# not a firehose, and so the node is not asked to record every log line an agent
# ever printed.
MIN_INTERVAL_S = 2.0
MAX_SUMMARY = 240


def classify(line):
    for pattern, kind in PATTERNS:
        m = pattern.search(line)
        if m:
            what = (m.groupdict().get("what") or "").strip()
            if what:
                return kind, what[:MAX_SUMMARY]
    return None, None


def report(cfg, kind, summary):
    url = cfg["service_url"] + "/v1/activity"
    payload = {"kind": kind, "summary": summary}
    r = requests.post(url, headers=auth_headers(cfg), json=payload, timeout=15)
    if r.status_code == 401:
        cfg = refresh_ucan(cfg)
        r = requests.post(url, headers=auth_headers(cfg), json=payload, timeout=15)
    return cfg


def follow(path):
    """Tail -F: survive the file not existing yet, and survive truncation."""
    while not os.path.exists(path):
        time.sleep(1)
    with open(path, "r", errors="replace") as f:
        f.seek(0, os.SEEK_END)
        while True:
            where = f.tell()
            line = f.readline()
            if not line:
                time.sleep(0.4)
                if os.path.getsize(path) < where:      # rotated / truncated
                    f.seek(0)
                continue
            yield line.rstrip("\n")


def main():
    p = argparse.ArgumentParser(description="report Spartan activity to the mesh")
    p.add_argument("--config", required=True, help="the entity's mesh identity")
    p.add_argument("--log", required=True, help="file Spartan's stdout is tee'd to")
    args = p.parse_args()

    with open(args.config) as f:
        cfg = json.load(f)

    print(f"[activity] reporting {cfg['entity_name']} -> {cfg['service_url']}/v1/activity")
    last = 0.0

    for line in follow(args.log):
        kind, summary = classify(line)
        if not kind:
            continue
        now = time.time()
        if now - last < MIN_INTERVAL_S:
            continue
        try:
            cfg = report(cfg, kind, summary) or cfg
            last = now
        except Exception as e:                                  # noqa: BLE001
            print(f"[activity] report failed ({e})", file=sys.stderr)
            time.sleep(2)


if __name__ == "__main__":
    main()
