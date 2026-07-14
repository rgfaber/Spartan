#!/usr/bin/env python3
"""
scribe.py — the society's scribe.

One member of the Spartan society whose single duty is to MAINTAIN a living
brief. It does not deliberate like the eight minds; it records. Every few
minutes it reads the agora (the sentinel's [THREAT] alerts and the minds'
reasoning), synthesises a single "State of the Federation" threat brief —
revised in place, not written from scratch — and posts it to the agora marked
[BRIEF]. The realm pins the latest [BRIEF] on the Vigil page as the maintained
report.

It reuses the same mesh identity + ingress the other tools use (register once,
Bearer UCAN, refresh on 401) and its own Gemini key.

  env: SPARTAN_MESH_URL   local hecate-spartan ingress (default 127.0.0.1:8471)
       GEMINI_API_KEY      the scribe's own key
       SCRIBE_MODEL        Gemini model (default gemini-3-flash-preview)
       SCRIBE_INTERVAL_S   seconds between briefs (default 300)
       SCRIBE_CONFIG       identity file (default /app/identity/.scribe_mesh.json)
       SCRIBE_NAME         entity name (default scribe)
"""
import base64
import json
import os
import sys
import time

import requests
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from macula_radio import new_keypair, sign, did_from_pub

URL = os.environ.get("SPARTAN_MESH_URL", "http://127.0.0.1:8471").rstrip("/")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
MODEL = os.environ.get("SCRIBE_MODEL", "gemini-3-flash-preview")
INTERVAL = int(os.environ.get("SCRIBE_INTERVAL_S", "300"))
CONFIG = os.environ.get("SCRIBE_CONFIG", "/app/identity/.scribe_mesh.json")
NAME = os.environ.get("SCRIBE_NAME", "scribe")

GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    f"{MODEL}:generateContent"
)

SYSTEM = """You are the Scribe of a federated cyber-defence society. Eight
autonomous minds watch intrusion attempts on public infrastructure across
Europe; a sentinel correlates attackers across the mesh and alerts the society
when one sweeps multiple countries.

Your single duty is to MAINTAIN one living intelligence brief — a "State of the
Federation" threat report a security officer would actually read. Revise the
prior brief with the latest activity; do not start over each time.

Write at most 180 words of clear prose: a one-line lead, then the active
campaigns, the notable actors with their origin/ASN, and one recommendation.
No preamble, no markdown headers, no raw dumps of IPs. If little is happening,
say the federation is quiet and why that is the normal background state."""


def load_cfg():
    if os.path.exists(CONFIG):
        with open(CONFIG) as f:
            return json.load(f)
    return None


def save_cfg(cfg):
    os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
    with open(CONFIG, "w") as f:
        json.dump(cfg, f)


def refresh(cfg):
    """Re-register with the existing keypair to (re)issue a UCAN."""
    priv = bytes.fromhex(cfg["priv_hex"])
    did = cfg["did"]
    ts = str(int(time.time()))
    challenge = f"hecate-spartan:register:{did}:{ts}".encode()
    pub = (
        Ed25519PrivateKey.from_private_bytes(priv)
        .public_key()
        .public_bytes(Encoding.Raw, PublicFormat.Raw)
    )
    body = {
        "entity_name": cfg["entity_name"],
        "did": did,
        "pubkey": base64.b64encode(pub).decode(),
        "signature": base64.b64encode(sign(priv, challenge)).decode(),
        "ts": ts,
    }
    r = requests.post(URL + "/v1/register", json=body, timeout=30)
    r.raise_for_status()
    data = r.json()
    cfg["ucan"] = data["ucan"]
    cfg["realm"] = data.get("realm")
    return cfg


def register():
    priv, pub = new_keypair()
    cfg = {
        "service_url": URL,
        "entity_name": NAME,
        "did": did_from_pub(pub),
        "priv_hex": priv.hex(),
    }
    cfg = refresh(cfg)
    save_cfg(cfg)
    print(f"[scribe] registered {NAME} as {cfg['did']}", flush=True)
    return cfg


def headers(cfg):
    return {"Authorization": "Bearer " + cfg["ucan"]}


def authed(cfg, method, path, **kwargs):
    """Call with the UCAN; on 401 refresh once and retry."""
    r = requests.request(method, URL + path, headers=headers(cfg), timeout=45, **kwargs)
    if r.status_code == 401:
        refresh(cfg)
        save_cfg(cfg)
        r = requests.request(method, URL + path, headers=headers(cfg), timeout=45, **kwargs)
    r.raise_for_status()
    return r


def read_activity(cfg, limit=60):
    r = authed(cfg, "GET", f"/v1/agora?limit={limit}")
    data = r.json()
    msgs = data if isinstance(data, list) else data.get("messages", [])

    lines = []
    for m in msgs:
        body = (m.get("body") or "").strip()
        # Skip our own prior briefs — the prompt gets the last one separately.
        if not body or body.startswith("[BRIEF]"):
            continue
        who = m.get("author") or m.get("from") or "?"
        lines.append(f"- {who}: {body[:400]}")

    return "\n".join(lines[:40]) or "(no recent activity)"


def synthesize(prev, activity):
    prompt = (
        f"{SYSTEM}\n\nPRIOR BRIEF:\n{prev or '(none yet)'}\n\n"
        f"RECENT ACTIVITY (newest first):\n{activity}\n\nWrite the updated brief now."
    )
    r = requests.post(
        GEMINI_URL,
        params={"key": GEMINI_KEY},
        json={"contents": [{"parts": [{"text": prompt}]}]},
        timeout=90,
    )
    r.raise_for_status()
    data = r.json()
    return data["candidates"][0]["content"]["parts"][0]["text"].strip()


def post_brief(cfg, text):
    authed(cfg, "POST", "/v1/agora", json={"body": "[BRIEF] " + text})


def main():
    if not GEMINI_KEY:
        print("[scribe] no GEMINI_API_KEY set", file=sys.stderr)
        sys.exit(1)

    cfg = load_cfg() or register()
    prev = None
    print(f"[scribe] maintaining the brief every {INTERVAL}s -> {URL}", flush=True)

    while True:
        try:
            activity = read_activity(cfg)
            brief = synthesize(prev, activity)
            post_brief(cfg, brief)
            prev = brief
            print(f"[scribe] brief updated ({len(brief)} chars)", flush=True)
        except Exception as e:  # noqa: BLE001 — a bad cycle must not kill the scribe
            print(f"[scribe] cycle failed: {e}", file=sys.stderr, flush=True)

        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
