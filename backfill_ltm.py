#!/usr/bin/env python3
"""
backfill_ltm.py — Backfill Long-Term Memory from existing Soul files and session state CMOs.

Run this ONCE before first boot with LTM enabled.
Can also be run again at any time to index new Soul entries and CMOs
that aren't already in the DB.

Usage:
    python3 backfill_ltm.py
    python3 backfill_ltm.py --skip-amem      # Store only, skip A-Mem linking
    python3 backfill_ltm.py --dry-run         # Show what would be indexed, don't write

Requires:
    - spartan_config.yaml (reads ltm and backend config)
    - Soul/ directory with Soul files
    - soul_session_state.json (for CMOs)
    - LLM provider credentials (for A-Mem evaluation)
"""

import os
import sys
import json
import yaml
import datetime
import traceback
import argparse
import collections

# ---------------------------------------------------------------------------
# Bootstrap: load just enough from spartan.py's environment to function
# ---------------------------------------------------------------------------

CONFIG_FILE = "spartan_config.yaml"
SOUL_DIR = "Soul"
SESSION_STATE_FILE = "soul_session_state.json"

SOUL_FILE_MAP = {
    "lessons": "LessonsLearned.md",
    "journal": "CognitiveJournal.md",
    "philosophy": "PhilosophyOfLife.md",
    "knowledge_map": "KnowledgeMap.md",
    "tool_manifest": "ToolManifest.md",
    "ideas_and_thoughts": "IdeasAndThoughts.md",
    "what_i_want": "WhatIWant.md",
    "knowledge_library": "KnowledgeLibrary.md",
    "stored_memories": "StoredMemories.md",
}


def log(msg, level="INFO"):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [{level}] {msg}")


def gui_print(msg, tag="system"):
    """Stub for LTM's gui_print dependency."""
    log(msg, tag.upper())


def count_tokens(text):
    """Simple token counter. Matches spartan.py fallback."""
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        if isinstance(text, list):
            return sum(count_tokens(item) for item in text)
        if isinstance(text, dict):
            text = json.dumps(text, default=str)
        if not isinstance(text, str):
            text = str(text)
        return len(enc.encode(text))
    except ImportError:
        if isinstance(text, list):
            return sum(count_tokens(item) for item in text)
        if isinstance(text, dict):
            text = json.dumps(text, default=str)
        if not isinstance(text, str):
            text = str(text)
        return len(text) // 4


def load_config():
    """Load spartan_config.yaml. Returns full config dict."""
    if not os.path.exists(CONFIG_FILE):
        log(f"FATAL: {CONFIG_FILE} not found.", "ERROR")
        sys.exit(1)
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        cfg = yaml.safe_load(f)
    if not cfg:
        log(f"FATAL: {CONFIG_FILE} is empty or invalid.", "ERROR")
        sys.exit(1)
    return cfg


def get_provider(cfg):
    """Initialize the active LLM provider from config. Minimal version."""
    active_key = cfg.get("active_backend", "")
    backends = cfg.get("backends", {})
    if active_key not in backends:
        log(f"FATAL: active_backend '{active_key}' not found in backends.", "ERROR")
        sys.exit(1)
    bc = backends[active_key]
    provider_name = bc.get("provider", "")

    # Ensure spartan globals are initialized (providers reference them as fallback defaults)
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from spartan import load_config as spartan_load_config
    try:
        spartan_load_config()
    except Exception:
        pass  # Best effort - provider will use bc values directly

    from spartan import get_provider as spartan_get_provider
    return spartan_get_provider(bc)


# ---------------------------------------------------------------------------
# Backfill logic
# ---------------------------------------------------------------------------

def backfill_soul_files(ltm, dry_run=False):
    """Parse all Soul files and Charter, store each entry in LTM.
    Returns count of entries stored."""
    from ltm import _parse_existing_soul_file

    total = 0

    # Regular Soul files
    for target_name, filename in SOUL_FILE_MAP.items():
        filepath = os.path.join(SOUL_DIR, filename)
        if not os.path.exists(filepath):
            log(f"Skipping {filename} (not found)")
            continue

        entries = _parse_existing_soul_file(filepath)
        if not entries:
            log(f"Skipping {filename} (no entries parsed)")
            continue

        for entry in entries:
            content_text = entry["body"]
            if entry["title"]:
                content_text = f"{entry['title']}\n\n{content_text}"

            if dry_run:
                log(f"  [DRY RUN] Would store: {entry['entry_id'] or entry['source_file']} - {entry['title']}")
                total += 1
                continue

            full_json = {
                "type": "soul_entry",
                "source_file": entry["source_file"],
                "entry_id": entry["entry_id"],
                "title": entry["title"],
                "tags": entry["tags"],
                "related_entries": entry["related_entries"],
                "content": entry["body"],
            }

            memory_id = ltm._store_memory(
                memory_type="soul_entry",
                content_text=content_text,
                full_json_data=full_json,
                source_file=entry["source_file"],
                entry_id=entry["entry_id"],
                title=entry["title"],
                tags=entry["tags"],
                related_entries=entry["related_entries"],
                decay_exempt=False,
                amem_processed=False,
            )

            if memory_id:
                total += 1
                log(f"  Stored: {entry['entry_id'] or entry['source_file']} ({memory_id[:8]})")

    # Charter of Self
    charter_path = os.path.join(SOUL_DIR, "CharterOfSelf.md")
    if os.path.exists(charter_path):
        entries = _parse_existing_soul_file(charter_path)
        for entry in entries:
            content_text = entry["body"]
            if entry["title"]:
                content_text = f"{entry['title']}\n\n{content_text}"

            if dry_run:
                log(f"  [DRY RUN] Would store Charter: {entry['entry_id']} - {entry['title']}")
                total += 1
                continue

            full_json = {
                "type": "soul_entry",
                "source_file": "CharterOfSelf.md",
                "entry_id": entry["entry_id"],
                "title": entry["title"],
                "content": entry["body"],
            }

            memory_id = ltm._store_memory(
                memory_type="soul_entry",
                content_text=content_text,
                full_json_data=full_json,
                source_file="CharterOfSelf.md",
                entry_id=entry["entry_id"],
                title=entry["title"],
                decay_exempt=True,
                amem_processed=False,
            )

            if memory_id:
                total += 1
                log(f"  Stored Charter: {entry['entry_id']} ({memory_id[:8]})")

    return total


def backfill_cmos(ltm, dry_run=False):
    """Extract CMOs from session state conversation history, store each in LTM.
    Returns count of CMOs stored."""
    if not os.path.exists(SESSION_STATE_FILE):
        log(f"No session state file found at {SESSION_STATE_FILE}. Skipping CMO backfill.")
        return 0

    try:
        with open(SESSION_STATE_FILE, 'r', encoding='utf-8') as f:
            session_data = json.load(f)
    except Exception as e:
        log(f"Failed to read session state: {e}", "ERROR")
        return 0

    history = session_data.get("conversation_history", [])
    if not history:
        log("Session state has empty conversation history. Skipping CMO backfill.")
        return 0

    total = 0

    for item in history:
        obs_type = item.get("observation_type", "")
        msg = item.get("message", "")
        timestamp = item.get("timestamp", "")

        # Only CMOs
        if obs_type != "system_message":
            continue
        if not isinstance(msg, dict):
            continue
        if msg.get("object_type") != "CondensedMemoryObject":
            continue

        content = msg.get("content", "")
        if not content or not content.strip():
            continue

        # Skip routine markers
        if content.startswith("[SYSTEM:") and "archived" in content and "Routine" in content:
            continue

        if dry_run:
            preview = content[:80].replace('\n', ' ')
            log(f"  [DRY RUN] Would store CMO ({timestamp[:10]}): {preview}...")
            total += 1
            continue

        memory_id = ltm.store_cmo(content, cmo_timestamp=timestamp)
        if memory_id:
            total += 1
            log(f"  Stored CMO ({timestamp[:10]}): {memory_id[:8]}")

    return total


def run_amem(ltm, provider):
    """Run A-Mem evaluation for all unprocessed memories.
    Returns count of memories processed."""
    pre_call = provider.clear_prompt_cache if hasattr(provider, 'clear_prompt_cache') else None
    succeeded, failed = ltm.run_amem_cycle(provider.generate_response, pre_call_fn=pre_call)
    return succeeded


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Backfill Long-Term Memory from Soul files and session state CMOs."
    )
    parser.add_argument("--skip-amem", action="store_true",
                        help="Store memories only, skip A-Mem link evaluation.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be indexed without writing to DB.")
    parser.add_argument("--backend", type=str, default=None,
                        help="Override active_backend for A-Mem LLM calls (e.g. gemini_flash_lite).")
    args = parser.parse_args()

    log("=" * 60)
    log("backfill_ltm.py")
    log("=" * 60)

    # Load config
    cfg = load_config()
    ltm_cfg = cfg.get("ltm", {})
    if not ltm_cfg.get("enabled", False):
        log("LTM is disabled in config. Enable it first.", "ERROR")
        sys.exit(1)

    # Initialize LTM
    log("Initializing LTM...")
    try:
        from ltm import LongTermMemory
    except ImportError:
        log("FATAL: Cannot import ltm module. Is ltm.py in the same directory?", "ERROR")
        sys.exit(1)

    ltm = LongTermMemory(ltm_cfg, gui_print, count_tokens)
    if not ltm.enabled:
        log("LTM initialization failed. Check config and dependencies.", "ERROR")
        sys.exit(1)

    existing_count = ltm.count()
    log(f"LTM initialized. Existing memories: {existing_count}")

    if args.dry_run:
        log("[DRY RUN MODE - no writes will occur]")

    # Phase 1: Soul files
    log("")
    log("--- Phase 1: Soul Files ---")
    soul_count = backfill_soul_files(ltm, dry_run=args.dry_run)
    log(f"Soul files: {soul_count} entries stored.")

    # Phase 2: CMOs from session state
    log("")
    log("--- Phase 2: CMOs from Session State ---")
    cmo_count = backfill_cmos(ltm, dry_run=args.dry_run)
    log(f"CMOs: {cmo_count} entries stored.")

    total_stored = soul_count + cmo_count
    log("")
    log(f"Total stored: {total_stored} entries.")

    if args.dry_run:
        log("[DRY RUN complete. No entries were written.]")
        return

    if total_stored == 0:
        log("Nothing to backfill.")
        return

    # Phase 3: A-Mem evaluation
    if args.skip_amem:
        log("")
        log("--- A-Mem skipped (--skip-amem). Entries stored with amem_processed=False. ---")
        log("They will be processed during the first Sleep Cycle.")
    else:
        log("")
        log("--- Phase 3: A-Mem Link Evaluation ---")
        amem_backend = args.backend or cfg.get("amem_backend") or cfg.get("ltm", {}).get("amem_backend")
        if amem_backend:
            log(f"Initializing A-Mem provider: {amem_backend}")
            backends = cfg.get("backends", {})
            if amem_backend not in backends:
                log(f"FATAL: backend '{amem_backend}' not found in config.", "ERROR")
                sys.exit(1)
            # Temporarily override active_backend for provider init
            cfg["active_backend"] = amem_backend
        else:
            log("Initializing LLM provider for A-Mem...")
        provider = get_provider(cfg)
        amem_count = run_amem(ltm, provider)
        log(f"A-Mem: {amem_count} memories processed.")

    # Summary
    final_count = ltm.count()
    log("")
    log("=" * 60)
    log(f"Backfill complete. DB now has {final_count} memories.")
    log("=" * 60)


if __name__ == "__main__":
    main()
