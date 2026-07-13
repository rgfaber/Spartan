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
# wins, so the specific patterns come first.
#
# The REASONING is the point. Spartan attaches a `thought` to every action it
# takes and prints it as "  Thought (ID:x): ...", and prints anything it says as
# "<Name>: ...". Those two lines are what makes an agent worth watching. The
# token-accounting lines ("API: in=49641") are deliberately NOT reported: they
# are a heartbeat, not a mind, and they drown everything else.
PATTERNS = [
    (re.compile(r"^\s*Thought \(ID:[^)]*\):\s*(?P<what>.+)"), "thought"),
    (re.compile(r"^\s*\[E:\d+\] THINKING:\s*(?P<what>.+)"), "thought"),
    (re.compile(r"^\s*\[EXEC\]\s*(?P<what>.+)"), "action"),
    (re.compile(r"\[E:\d+\] ACTION:\s*(?P<what>.+)"), "action"),
    (re.compile(r"\[Message From:\s*(?P<what>[^\]]+)\]"), "alert"),
    (re.compile(r"CMO complete:\s*(?P<what>.+)"), "cycle"),
]

# Speech is printed as "<PersonaName>: <text>" with no tag, so it can only be
# recognised once we know the entity's own name.
SPEECH = None

# A cognition cycle is chatty. Cap the rate so the page shows a train of thought,
# not a firehose.
MIN_INTERVAL_S = 1.5
MAX_SUMMARY = 400


def classify(line):
    if SPEECH:
        m = SPEECH.match(line)
        if m:
            return "speech", m.group("what").strip()[:MAX_SUMMARY]

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

    # An entity that has renamed itself speaks under its chosen name, so match on
    # the config name OR whatever the running Spartan calls itself.
    global SPEECH
    SPEECH = re.compile(r"^(?P<who>[A-Za-z0-9_\-]{2,32}):\s+(?P<what>.{4,})")

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
