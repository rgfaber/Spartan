#!/usr/bin/env python3
"""
librarian.py — the society's shared knowledge base, kept beside the scribe.

The beam minds run on Celerons that can't run LanceDB, so they have no deep
vector recall. This service — co-located with the LTM scribe on msi00 (AVX2 +
the Ollama embedding model) — gives the whole society ONE shared, queryable
memory over the mesh. A mind sends a DIRECT message:

    [REMEMBER] <text>     -> embedded and stored in the knowledge base
    [RECALL] <query>      -> the top matches are sent back as a direct message

Deterministic on purpose: a lookup always gets an answer. The autonomous scribe
mind writes the BRIEF; this librarian answers LOOKUPS. Same node, same embedding
model, a distinct store — so the shared knowledge base is never entangled with
any one mind's private LTM.

  env: SPARTAN_MESH_URL   local hecate-spartan ingress (default 127.0.0.1:8471)
       OLLAMA_HOST        default http://127.0.0.1:11434
       EMBED_MODEL        default qwen3-embedding:0.6b-q8_0
       KB_PATH            LanceDB dir (default /app/kb)
       LIBRARIAN_CONFIG   identity file
       LIBRARIAN_NAME     entity name (default librarian)
       RECALL_K           matches per recall (default 4)
"""
import json
import os
import sys
import time

import base64
import requests
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from macula_radio import new_keypair, sign, did_from_pub
import lancedb
import pyarrow as pa

URL = os.environ.get("SPARTAN_MESH_URL", "http://127.0.0.1:8471").rstrip("/")
OLLAMA = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
EMBED_MODEL = os.environ.get("EMBED_MODEL", "qwen3-embedding:0.6b-q8_0")
KB_PATH = os.environ.get("KB_PATH", "/app/kb")
CONFIG = os.environ.get("LIBRARIAN_CONFIG", "/app/identity/.librarian_mesh.json")
NAME = os.environ.get("LIBRARIAN_NAME", "librarian")
RECALL_K = int(os.environ.get("RECALL_K", "4"))

REMEMBER = "[REMEMBER]"
RECALL = "[RECALL]"


# ── mesh identity (same register/auth discipline as the other tools) ──

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
    cfg["ucan"] = r.json()["ucan"]
    return cfg


def register():
    priv, pub = new_keypair()
    cfg = {"service_url": URL, "entity_name": NAME,
           "did": did_from_pub(pub), "priv_hex": priv.hex()}
    cfg = refresh(cfg)
    save_cfg(cfg)
    print(f"[librarian] registered {NAME} as {cfg['did']}", flush=True)
    return cfg


def headers(cfg):
    return {"Authorization": "Bearer " + cfg["ucan"]}


def send(cfg, to, body):
    for _ in range(2):
        r = requests.post(URL + "/v1/send", headers=headers(cfg),
                          json={"to": to, "body": body}, timeout=30)
        if r.status_code == 401:
            refresh(cfg)
            save_cfg(cfg)
            continue
        return r.ok
    return False


# ── embeddings + the knowledge base (LanceDB) ──

def embed(text):
    r = requests.post(OLLAMA + "/api/embeddings",
                      json={"model": EMBED_MODEL, "prompt": text}, timeout=60)
    r.raise_for_status()
    return r.json()["embedding"]


def open_kb():
    db = lancedb.connect(KB_PATH)
    if "knowledge" in db.table_names():
        return db.open_table("knowledge")
    dim = len(embed("dimension probe"))
    schema = pa.schema([
        pa.field("vector", pa.list_(pa.float32(), dim)),
        pa.field("text", pa.string()),
        pa.field("source", pa.string()),
        pa.field("ts", pa.int64()),
    ])
    print(f"[librarian] knowledge base created (dim {dim}) at {KB_PATH}", flush=True)
    return db.create_table("knowledge", schema=schema)


def remember(tbl, text, source):
    tbl.add([{
        "vector": embed(text),
        "text": text,
        "source": source,
        "ts": int(time.time() * 1000),
    }])


def recall(tbl, query, k=RECALL_K):
    try:
        return tbl.search(embed(query)).limit(k).to_list()
    except Exception as e:  # noqa: BLE001 — an empty/young table must not throw
        print(f"[librarian] recall search failed: {e}", file=sys.stderr, flush=True)
        return []


def format_reply(query, hits):
    if not hits:
        return f"[RECALL] nothing in the shared knowledge base yet for: {query}"
    lines = [f"[RECALL] {len(hits)} memories for: {query}"]
    for i, h in enumerate(hits, 1):
        lines.append(f"{i}. {(h.get('text') or '')[:300]}")
    return "\n".join(lines)


# ── the request handler ──

def handle(cfg, tbl, frm, body):
    if body.startswith(REMEMBER):
        text = body[len(REMEMBER):].strip()
        if text:
            remember(tbl, text, frm)
            print(f"[librarian] remembered {len(text)}c from {frm[:24]}", flush=True)
    elif body.startswith(RECALL):
        query = body[len(RECALL):].strip()
        if query:
            reply = format_reply(query, recall(tbl, query))
            send(cfg, frm, reply)
            print(f"[librarian] recalled for {frm[:24]}: {query[:60]}", flush=True)


def receive_loop(cfg, tbl):
    print(f"[librarian] listening on {URL}/v1/receive", flush=True)
    while True:
        try:
            with requests.get(URL + "/v1/receive", headers=headers(cfg),
                              stream=True, timeout=None) as resp:
                if resp.status_code == 401:
                    refresh(cfg)
                    save_cfg(cfg)
                    continue
                resp.raise_for_status()
                for raw in resp.iter_lines():
                    if not raw or not raw.startswith(b"data: "):
                        continue
                    msg = json.loads(raw[len(b"data: "):])
                    # Direct messages only — the KB is a private desk, not the agora.
                    if msg.get("agora") or msg.get("broadcast"):
                        continue
                    handle(cfg, tbl, msg.get("from", ""), (msg.get("body") or "").strip())
        except requests.exceptions.RequestException as e:
            print(f"[librarian] receive disconnected ({e}); retry in 5s",
                  file=sys.stderr, flush=True)
            time.sleep(5)


def main():
    tbl = open_kb()
    cfg = load_cfg() or register()
    receive_loop(cfg, tbl)


if __name__ == "__main__":
    main()
