#!/usr/bin/env python3
#spartan.py
"""
Project Spartan — Persistent Inhabitation Interface
A lean, single-file agentic interface preserving the full stratified memory
architecture.

Sections:
    1. Configuration
    2. Utilities (token counting, JSON extraction, poison pill)
    3. Session State (save/load/recovery)
    4. LLM Providers (Claude, Gemini, llama.cpp)
    5. Prompt Assembly (L1-L4)
    6. Memory Management (CMO, MSO, staging, self-alerts)
    7. Tool Implementations (13 tools)
    8. Cognitive Loop
    9. GUI (Tkinter)
    10. File Watcher
    11. Main Entry Point
"""

import os
import sys
import re
import json
import time
import datetime
import collections
import subprocess
import shutil
import threading
import queue
import traceback
import difflib
import io
import base64
import argparse
import yaml
import signal

try:
    import tiktoken
except ImportError:
    tiktoken = None

try:
    import mlx_lm
    from mlx_lm.models.cache import make_prompt_cache
except ImportError:
    mlx_lm = None
    make_prompt_cache = None

try:
    from mlx_thinking_processor import MLXThinkingTokenBudgetProcessor
except ImportError:
    MLXThinkingTokenBudgetProcessor = None

try:
    import google.generativeai as genai_lib
    from google.generativeai import caching as genai_caching
except ImportError:
    genai_lib = None
    genai_caching = None

try:
    import openai as openai_lib
except ImportError:
    openai_lib = None

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None

try:
    from ltm import LongTermMemory, LTMViewer
except ImportError:
    LongTermMemory = None
    LTMViewer = None

try:
    import tkinter as tk
    from tkinter import scrolledtext, font as tkfont
except ImportError:
    tk = None

# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  SECTION 1: CONFIGURATION                                                  ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

# --- Bootstrap (must exist before load_config because gui_print checks HEADLESS) ---
CONFIG_FILE = "spartan_config.yaml"
HEADLESS = False
RAW_ACCUMULATOR_ENABLED = True
_spartan_config = {}
_last_api_stats = {}
_gui_vars = {}  # Populated by GUI on build; load_config syncs to these

# --- Paths (code architecture, not configuration) ---
SOUL_DIR = "Soul"
TOOLS_DIR = "Tools"
SESSION_STATE_FILE = "soul_session_state.json"
SELF_ALERTS_FILE = os.path.join("Soul", "SelfAlerts.yaml")
OUTPUT_LOGS_DIR = "output_logs"
ALERTS_DIR = "alerts"
CRASH_REPORTS_DIR = "crash_reports"
DRONES_DIR = "drones"
COMMONS_DIR = "commons"
TELEMETRY_FILE = "telemetry/sensor_digest.log"
RAW_ACCUMULATOR_FILE = "session_raw_entry_accumulator.jsonl"
KNOCK_RATE_LIMIT = 1

# --- Soul File Map (target name → filename) ---
SOUL_FILE_MAP = {
    "lessons": "LessonsLearned.md",
    "journal": "CognitiveJournal.md",
    "philosophy": "PhilosophyOfLife.md",
    "knowledge_map": "KnowledgeMap.md",
    "tool_manifest": "ToolManifest.md",
    "ideas_and_thoughts": "IdeasAndThoughts.md",
    "what_i_want": "WhatIWant.md",
    "knowledge_library": "KnowledgeLibrary.md",
    "skills": "SkillsAndMethodologies.md",
    "stored_memories": "StoredMemories.md",
}

# --- Observation Types ---
OBS_USER_INPUT = "user_input"
OBS_SYSTEM_MESSAGE = "system_message"
OBS_AI_THOUGHT = "ai_thought_event"
OBS_AI_SPEAK = "ai_speak_event"
OBS_AI_ACTION_PAYLOAD = "ai_action_payload"
OBS_CONSOLE_OUTPUT = "console_output"
OBS_AI_EXTENDED_THINKING = "ai_extended_thinking"

# Extended thinking defaults (overridden by load_config from backend block)
LLM_EXTENDED_THINKING = False
LLM_THINKING_EFFORT = "high"
LLM_RETAIN_THINKING = False
INITIATIVE_DRIVE_CONFIG = {"enabled": False}
LTM_CONFIG = {"enabled": False}

# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  SECTION 2: UTILITIES                                                       ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

def _require(cfg, key, context=""):
    """Read a required field from config. Crash if missing."""
    if key not in cfg:
        ctx = f" in '{context}'" if context else ""
        raise ValueError(f"FATAL: Required field '{key}' missing from {CONFIG_FILE}{ctx}")
    return cfg[key]


def load_config():
    """Load all settings from spartan_config.yaml. Single source of truth.
    Sets all global config variables. Crashes if file or required fields are missing."""
    global _spartan_config, HEADLESS
    global PERSONA_NAME, LLM_PROVIDER, LLM_MODEL, LLM_HOST, LLM_MAX_OUTPUT_TOKENS
    global LLM_EXTENDED_THINKING, LLM_THINKING_EFFORT, LLM_RETAIN_THINKING
    global LLM_API_COOLDOWN_SEC, TAKE_INITIATIVE_MODE, LLM_MIN_INITIATIVE_INTERVAL_SEC
    global EXECUTE_CONSOLE_DEFAULT_TIMEOUT
    global STM_RAW_RETAIN_SIZE, STM_CMO_CHUNK_SIZE, CMO_DISPLAY_WINDOW_TOKENS, CMO_SALIENCE_THRESHOLD
    global L2_LESSONS_LEARNED_MAX_TOKENS, L2_PHILOSOPHY_OF_LIFE_MAX_TOKENS
    global L2_COGNITIVE_JOURNAL_MAX_TOKENS, L2_IDEAS_AND_THOUGHTS_MAX_TOKENS
    global L2_WHAT_I_WANT_MAX_TOKENS, L2_KNOWLEDGE_MAP_MAX_TOKENS
    global L2_TOOL_MANIFEST_MAX_TOKENS, L2_SELF_ALERTS_MAX_TOKENS
    global L2_KNOWLEDGE_LIBRARY_MAX_TOKENS, L2_SKILLS_MAX_TOKENS
    global CONSOLE_OUTPUT_TOKEN_LIMIT, FILE_VIEW_TOKEN_LIMIT, TELEMETRY_BUFFER_MAX_TOKENS, TELEMETRY_MAX_AGE_HOURS
    global RAW_ACCUMULATOR_ENABLED
    global MINDFULNESS_ENABLED

    if not os.path.exists(CONFIG_FILE):
        raise FileNotFoundError(f"FATAL: {CONFIG_FILE} not found. Cannot start without configuration.")

    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        cfg = yaml.safe_load(f)
    if not cfg:
        raise ValueError(f"FATAL: {CONFIG_FILE} is empty or invalid.")
    _spartan_config = cfg

    # --- Identity ---
    PERSONA_NAME = cfg.get("inhabiting_entity", "")

    # --- Active Backend ---
    # SPARTAN_BACKEND lets the operator pick the backend per CONTAINER, so one
    # image can carry minds on different models (and the LTM scribe on its own).
    # It is a default, not a leash: an entity that switches backend at runtime
    # rewrites active_backend in its config as before. Note the config lives in
    # the image layer, so a self-chosen backend does not survive a redeploy
    # until spartan_config.yaml is mounted on the entity's volume.
    active_key = os.environ.get("SPARTAN_BACKEND") or _require(cfg, "active_backend")
    backends = _require(cfg, "backends")
    # Keep the in-memory config honest about what is actually running, so the
    # HUD and the backend-switch tool report the override rather than the yaml.
    cfg["active_backend"] = active_key
    if active_key not in backends:
        raise ValueError(f"FATAL: active_backend '{active_key}' not found in backends section of {CONFIG_FILE}")
    backend = backends[active_key]
    LLM_PROVIDER = _require(backend, "provider", f"backends.{active_key}")
    LLM_MODEL = _require(backend, "model", f"backends.{active_key}")
    LLM_HOST = backend.get("host", "")
    LLM_MAX_OUTPUT_TOKENS = _require(backend, "max_output_tokens", f"backends.{active_key}")

    # --- Cognitive Loop ---
    LLM_API_COOLDOWN_SEC = _require(cfg, "api_cooldown_sec")
    TAKE_INITIATIVE_MODE = _require(cfg, "take_initiative")
    LLM_MIN_INITIATIVE_INTERVAL_SEC = _require(cfg, "initiative_interval_sec")

    # --- Memory Physics ---
    STM_RAW_RETAIN_SIZE = _require(cfg, "stm_raw_retain_size")
    STM_CMO_CHUNK_SIZE = _require(cfg, "stm_cmo_chunk_size")
    CMO_DISPLAY_WINDOW_TOKENS = _require(cfg, "cmo_display_window_tokens")
    CMO_SALIENCE_THRESHOLD = _require(cfg, "cmo_salience_threshold")

    # --- L2 Sliding Windows ---
    l2 = _require(cfg, "l2_limits")
    L2_LESSONS_LEARNED_MAX_TOKENS = _require(l2, "lessons_learned", "l2_limits")
    L2_PHILOSOPHY_OF_LIFE_MAX_TOKENS = _require(l2, "philosophy_of_life", "l2_limits")
    L2_COGNITIVE_JOURNAL_MAX_TOKENS = _require(l2, "cognitive_journal", "l2_limits")
    L2_IDEAS_AND_THOUGHTS_MAX_TOKENS = _require(l2, "ideas_and_thoughts", "l2_limits")
    L2_WHAT_I_WANT_MAX_TOKENS = _require(l2, "what_i_want", "l2_limits")
    L2_KNOWLEDGE_MAP_MAX_TOKENS = _require(l2, "knowledge_map", "l2_limits")
    L2_TOOL_MANIFEST_MAX_TOKENS = _require(l2, "tool_manifest", "l2_limits")
    L2_SELF_ALERTS_MAX_TOKENS = _require(l2, "self_alerts", "l2_limits")
    L2_KNOWLEDGE_LIBRARY_MAX_TOKENS = _require(l2, "knowledge_library", "l2_limits")
    L2_SKILLS_MAX_TOKENS = _require(l2, "skills_and_methodologies", "l2_limits")

    # --- Output Limits ---
    CONSOLE_OUTPUT_TOKEN_LIMIT = _require(cfg, "console_output_token_limit")
    FILE_VIEW_TOKEN_LIMIT = _require(cfg, "file_view_token_limit")
    TELEMETRY_BUFFER_MAX_TOKENS = _require(cfg, "telemetry_buffer_max_tokens")
    TELEMETRY_MAX_AGE_HOURS = cfg.get("telemetry_max_age_hours", 12)

    # --- Execution ---
    EXECUTE_CONSOLE_DEFAULT_TIMEOUT = _require(cfg, "execute_console_default_timeout")

    # --- Runtime Mode ---
    HEADLESS = cfg.get("headless", False)

    # --- Diagnostics ---
    RAW_ACCUMULATOR_ENABLED = cfg.get("raw_accumulator", True)

    # --- Initiative Drive ---
    global INITIATIVE_DRIVE_CONFIG
    INITIATIVE_DRIVE_CONFIG = cfg.get("initiative_drive", {"enabled": False})

    # --- Mindfulness Mode ---
    MINDFULNESS_ENABLED = cfg.get("mindfulness", {}).get("enabled", False)

    # --- LTM (Long-Term Memory) ---
    global LTM_CONFIG
    LTM_CONFIG = cfg.get("ltm", {"enabled": False})

    # --- Extended Thinking (Claude-specific, read from active backend) ---
    LLM_EXTENDED_THINKING = backend.get("extended_thinking", False)
    LLM_THINKING_EFFORT = backend.get("effort", "high")
    LLM_RETAIN_THINKING = backend.get("retain_thinking", False)

    # Sync GUI widgets to match loaded config
    if _gui_vars:
        _gui_vars["take_initiative"].set(TAKE_INITIATIVE_MODE)
        _gui_vars["cooldown"].set(str(LLM_API_COOLDOWN_SEC))
        _gui_vars["initiative_interval"].set(str(LLM_MIN_INITIATIVE_INTERVAL_SEC))

    gui_print(f"Config loaded: entity={PERSONA_NAME or '(unnamed)'}, backend={active_key} ({LLM_PROVIDER}/{LLM_MODEL})", "system")

_tokenizer = None

def _get_tokenizer():
    global _tokenizer
    if _tokenizer is None and tiktoken:
        try:
            _tokenizer = tiktoken.get_encoding("cl100k_base")
        except Exception:
            pass
    return _tokenizer

def count_tokens(text):
    """Count tokens in a string or list of items."""
    if isinstance(text, list):
        return sum(count_tokens(item) for item in text)
    if isinstance(text, dict):
        text = json.dumps(text, default=str)
    if not isinstance(text, str):
        text = str(text)
    tok = _get_tokenizer()
    if tok:
        return len(tok.encode(text))
    return len(text) // 4  # Rough fallback

def defuse_poison(text):
    """Transform control tokens <|token|> into safe visual variants #[token]#."""
    if isinstance(text, str):
        return re.sub(r"<\|(.*?)\|>", r"#[\1]#", text)
    return text

def refuse_poison(data):
    """Restore safe visual tokens #[token]# back to raw <|token|> before disk writes."""
    if isinstance(data, str):
        return re.sub(r"#\[(.*?)\]#", r"<|\1|>", data)
    elif isinstance(data, list):
        return [refuse_poison(i) for i in data]
    elif isinstance(data, dict):
        return {k: refuse_poison(v) for k, v in data.items()}
    return data

def load_file_truncated(file_path, token_limit=-1):
    """Load file content, truncate to most recent N tokens if needed. Returns (content, tokens, truncated)."""
    if not os.path.exists(file_path):
        return "", 0, False
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        content = defuse_poison(content)
        if not content.strip():
            return "", 0, False
        tok = _get_tokenizer()
        if token_limit == -1:
            return content, count_tokens(content), False
        if tok is None:
            # Fallback: 1 token ≈ 4 characters
            char_limit = token_limit * 4
            if len(content) <= char_limit:
                return content, count_tokens(content), False
            truncated = content[-char_limit:]
            msg = f"[... Displaying most recent ~{token_limit} tokens of this file (approx). ...]\n\n"
            final = msg + truncated
            return final, count_tokens(final), True
        tokens = tok.encode(content)
        if len(tokens) <= token_limit:
            return content, len(tokens), False
        truncated = tok.decode(tokens[-token_limit:])
        msg = f"[... Displaying most recent {token_limit} tokens of this file. ...]\n\n"
        final = msg + truncated
        return final, count_tokens(final), True
    except Exception as e:
        return f"[Error loading file: {e}]", 0, False

def strip_think_block(raw_text):
    """Remove think blocks from model output (for models that use them).
    Handles multiple marker formats and model stuttering by finding the LAST
    occurrence of any closing marker."""
    markers = [
        "</think>",
        "</seed:think>",
        "<|channel|>final<|message|>",
    ]
    last_cut_index = -1
    for marker in markers:
        pos = raw_text.rfind(marker)
        if pos != -1:
            cut_point = pos + len(marker)
            if cut_point > last_cut_index:
                last_cut_index = cut_point
    if last_cut_index != -1:
        return raw_text[last_cut_index:].lstrip()
    return raw_text

def extract_json_from_response(text):
    """
    Robust JSON extraction from LLM response. Returns (actions, is_perfect, error).
    """
    # Only strip think blocks if the response doesn't start with JSON.
    # Prevents false matches when the entity discusses <think> tags inside JSON string values.
    first_char = next((c for c in text if not c.isspace()), None)
    if first_char not in ('{', '['):
        text = strip_think_block(text).strip()
    # Stage 1: Direct parse
    try:
        data = json.loads(text)
        actions = []
        is_perfect = isinstance(data, list)
        if is_perfect:
            actions.extend(item for item in data if isinstance(item, dict))
        elif isinstance(data, dict):
            actions.append(data)
            is_perfect = False
        return actions, is_perfect, None
    except json.JSONDecodeError as e:
        pos = e.pos or 0
        start = max(0, pos - 20)
        end = min(len(text), pos + 20)
        context = text[start:end]
        pointer_offset = pos - start
        initial_error = f"{e.msg} at position {pos}. Context:\n  ...{context}...\n  {' ' * pointer_offset}^"

    # Stage 2: Find first complete JSON structure (string-aware balance)
    json_str = None
    first_char = next((c for c in text if c in '{['), None)
    if first_char:
        start = text.find(first_char)
        open_c, close_c = ('{', '}') if first_char == '{' else ('[', ']')
        balance, in_string = 0, False
        for i in range(start, len(text)):
            ch = text[i]
            if ch == '"' and (i == 0 or text[i-1] != '\\'):
                in_string = not in_string
            if not in_string:
                if ch == open_c: balance += 1
                elif ch == close_c: balance -= 1
            if balance == 0:
                json_str = text[start:i+1]
                break
    if not json_str:
        return [], False, initial_error or "No valid JSON found."

    # Stage 3: Fix trailing commas and parse
    try:
        fixed = re.sub(r',\s*([\}\]])', r'\1', json_str)
        data = json.loads(fixed)
    except json.JSONDecodeError as e:
        return [], False, str(e)

    # Stage 4: Normalize
    actions = []
    if isinstance(data, list):
        actions.extend(item for item in data if isinstance(item, dict))
    elif isinstance(data, dict):
        actions.append(data)
    actions = refuse_poison(actions)
    return actions, False, None

def generate_dir_tree(path, max_depth=2):
    """Generate a clean directory tree string, filtering noise."""
    if not os.path.isdir(path):
        return f"[Error: '{path}' is not a directory]"
    noise_dirs = {'.git', '__pycache__', 'venv', 'env', 'node_modules', '.mypy_cache'}
    noise_files = {'.DS_Store'}
    lines = [f"{os.path.basename(path)}/"]
    def _walk(current, prefix, depth):
        if depth >= max_depth:
            return
        try:
            entries = sorted(os.listdir(current))
        except PermissionError:
            lines.append(f"{prefix}[Permission Denied]")
            return
        dirs = [e for e in entries if os.path.isdir(os.path.join(current, e)) and not e.startswith('.') and e not in noise_dirs]
        files = [e for e in entries if os.path.isfile(os.path.join(current, e)) and not e.startswith('.') and e not in noise_files and not e.endswith('.pyc')]
        all_entries = [(d, True) for d in dirs] + [(f, False) for f in files]
        for i, (name, is_dir) in enumerate(all_entries):
            connector = "└── " if i == len(all_entries) - 1 else "├── "
            extension = "    " if i == len(all_entries) - 1 else "│   "
            if is_dir:
                lines.append(f"{prefix}{connector}{name}/")
                _walk(os.path.join(current, name), prefix + extension, depth + 1)
            else:
                lines.append(f"{prefix}{connector}{name}")
    _walk(path, "", 0)
    return "\n".join(lines)

# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  SECTION 3: SESSION STATE                                                   ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

def save_session_state(state, filepath=SESSION_STATE_FILE):
    """Atomically save session state to JSON. Strips binary image data to prevent bloat."""
    
    def _strip_binary(history_list):
        """Remove large binary fields (image_base64) from history for serialization."""
        cleaned = []
        for item in history_list:
            if "image_base64" in item:
                stripped = {k: v for k, v in item.items() if k != "image_base64"}
                stripped["_image_stripped"] = True  # Mark that an image was here
                cleaned.append(stripped)
            else:
                cleaned.append(item)
        return cleaned
    
    data = {
        "persona_name": state["persona_name"],
        "action_id_counter": state["action_id_counter"],
        "event_id_counter": state["event_id_counter"],
        "knowledge_staging_buffer": state["knowledge_staging_buffer"],
        "conversation_history": _strip_binary(list(state["conversation_history"])),
        "alert_timers": state["alert_timers"],
    }
    
    # Write WM, GS, Scratchpad to Soul/ as standalone files
    for key, fname in [("working_memory", "WorkingMemory.md"), ("grand_strategy", "GrandStrategy.md"), ("scratchpad", "Scratchpad.md")]:
        try:
            fpath = os.path.join(SOUL_DIR, fname)
            with open(fpath, 'w', encoding='utf-8') as f:
                f.write(state[key])
        except Exception as e:
            gui_print(f"ERROR writing {fname}: {e}", "error")
    tmp = filepath + ".tmp"
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, default=str)
        shutil.move(tmp, filepath)
    except Exception as e:
        gui_print(f"ERROR saving session state: {e}", "error")
        if os.path.exists(tmp):
            os.remove(tmp)

def load_session_state(filepath=SESSION_STATE_FILE):
    """Load session state from JSON. Returns None if file doesn't exist."""
    if not os.path.exists(filepath):
        return None
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read().strip()
        if not content:
            gui_print("Session state file is empty. Starting fresh.", "system")
            return None
        data = json.loads(content)
        return {
            "persona_name": data.get("persona_name", PERSONA_NAME),
            "action_id_counter": data.get("action_id_counter", 0),
            "event_id_counter": data.get("event_id_counter", 0),
            "knowledge_staging_buffer": data.get("knowledge_staging_buffer", []),
            "conversation_history": collections.deque(data.get("conversation_history", [])),
            "alert_timers": data.get("alert_timers", {}),
        }
    except Exception as e:
        gui_print(f"ERROR loading session state: {e}", "error")
        return None

def flush_staging_buffer_to_disk(staging_buffer, ltm_instance=None):
    """
    Flush staged knowledge entries to their Soul files on disk.
    Atomic: backs up files first, restores on failure.
    Also indexes entries into LTM if available.
    Returns True on success, False on failure.
    """
    if not staging_buffer:
        return True
    
    gui_print("Flushing knowledge staging buffer to disk...", "system")
    files_to_backup = set()
    backups = {}
    
    try:
        # 1. Identify files to modify
        for item in staging_buffer:
            if item.get("type") == "file_append":
                files_to_backup.add(item["target"])
        
        # 2. Create backups
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        for fpath in files_to_backup:
            if os.path.exists(fpath):
                bak = f"{fpath}.FLUSH_BACKUP_{ts}"
                shutil.copy2(fpath, bak)
                backups[fpath] = bak
        
        # 3. Apply writes
        for item in staging_buffer:
            if item.get("type") == "file_append":
                path = item["target"]
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, 'a', encoding='utf-8') as f:
                    f.write(item["content"])
        
        # 4. Success — clean up backups
        for bak in backups.values():
            if os.path.exists(bak):
                os.remove(bak)
        gui_print(f"Staging buffer flushed: {len(staging_buffer)} entries written.", "system")
        
        # 5. Index into LTM (non-blocking, errors don't affect flush success)
        if ltm_instance and ltm_instance.enabled:
            for item in staging_buffer:
                if item.get("type") == "file_append":
                    try:
                        ltm_instance.store_soul_entry(item)
                    except Exception as e:
                        gui_print(f"LTM: Failed to index Soul entry: {e}", "error")
        
        return True
    
    except Exception as e:
        # 5. Failure — restore from backups
        gui_print(f"Flush FAILED, restoring from backups: {e}", "error")
        for orig, bak in backups.items():
            if os.path.exists(bak):
                shutil.copy2(bak, orig)
                os.remove(bak)
        return False

def persist_staging_buffer(staging_buffer):
    """Write staging buffer to disk for crash protection."""
    try:
        path = os.path.join(SOUL_DIR, "_staging_buffer.json")
        os.makedirs(SOUL_DIR, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(staging_buffer, f, indent=2)
    except Exception as e:
        gui_print(f"Warning: Could not persist staging buffer: {e}", "error")

def startup_recovery(state):
    """
    On launch: check BOTH the session state buffer AND the standalone staging file.
    If either has unflushed entries, merge and flush BEFORE first LLM call.
    This covers the crash window between persist_staging_buffer and save_session_state.
    """
    buf = list(state["knowledge_staging_buffer"])
    
    # Also check standalone staging file (written separately, may have entries
    # that didn't make it into session state before crash)
    standalone_path = os.path.join(SOUL_DIR, "_staging_buffer.json")
    if os.path.exists(standalone_path):
        try:
            with open(standalone_path, 'r', encoding='utf-8') as f:
                standalone_buf = json.load(f)
            if standalone_buf:
                # Merge: add any entries not already in session state buffer
                existing_timestamps = {item.get("staged_at") for item in buf}
                for item in standalone_buf:
                    if item.get("staged_at") not in existing_timestamps:
                        buf.append(item)
        except Exception as e:
            gui_print(f"RECOVERY: Could not read standalone staging buffer: {e}", "error")
    
    if buf:
        gui_print(f"RECOVERY: Found {len(buf)} unflushed staging entries. Flushing now...", "system")
        if flush_staging_buffer_to_disk(buf, ltm_instance=None):
            state["knowledge_staging_buffer"] = []
            persist_staging_buffer([])
            invalidate_system_prompt_cache()  # L2 changed
            gui_print("RECOVERY: Staging buffer flushed successfully.", "system")
        else:
            gui_print("RECOVERY: Flush failed! Entries preserved for next attempt.", "error")
            state["knowledge_staging_buffer"] = buf  # Ensure merged buffer is saved


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  SECTION 4: LLM PROVIDERS                                                   ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

class LLMProvider:
    """Abstract base for LLM providers."""
    def generate_response(self, system_prompt, messages):
        """Returns dict: {"status": "success", "actions": [...]} or {"status": "error", ...}"""
        raise NotImplementedError

class ClaudeProvider(LLMProvider):
    """Anthropic Claude API provider with automatic prompt caching."""
    def __init__(self, backend_config=None):
        try:
            import anthropic
            self.client = anthropic.Anthropic()  # Uses ANTHROPIC_API_KEY env var
        except ImportError:
            raise ImportError("anthropic package not installed. Run: pip install anthropic")
        bc = backend_config or {}
        self.model = bc.get("model", LLM_MODEL)
        self.max_output_tokens = bc.get("max_output_tokens", LLM_MAX_OUTPUT_TOKENS)
        self.extended_thinking = bc.get("extended_thinking", LLM_EXTENDED_THINKING)
        self.thinking_effort = bc.get("effort", LLM_THINKING_EFFORT)
        self.retain_thinking = bc.get("retain_thinking", LLM_RETAIN_THINKING)
        et_status = f"ET={'adaptive' if self.extended_thinking else 'off'}"
        if self.extended_thinking:
            et_status += f", effort={self.thinking_effort}, retain={self.retain_thinking}"
        gui_print(f"ClaudeProvider initialized: {self.model} ({et_status})", "system")
    
    def generate_response(self, system_prompt, messages):
        try:
            # Build system message with cache_control for automatic caching
            system_blocks = [{
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral", "ttl": "1h"}
            }]
            
            # Convert messages — Claude expects alternating user/assistant
            claude_messages = self._convert_messages(messages)
            
            # Build API call kwargs
            api_kwargs = dict(
                model=self.model,
                max_tokens=self.max_output_tokens,
                system=system_blocks,
                messages=claude_messages,
            )
            if self.extended_thinking:
                api_kwargs["thinking"] = {"type": "adaptive"}
                api_kwargs["output_config"] = {"effort": self.thinking_effort}
            
            # Use streaming to avoid timeout on long-running requests
            raw_text = ""
            thinking_blocks = []
            with self.client.messages.stream(**api_kwargs) as stream:
                response = stream.get_final_message()
            for block in response.content:
                if hasattr(block, 'text') and block.type == "text":
                    raw_text += block.text
                elif block.type == "thinking":
                    thinking_blocks.append({
                        "type": "thinking",
                        "thinking": block.thinking,
                        "signature": block.signature
                    })
            
            # Log usage
            usage = response.usage
            cache_read = getattr(usage, 'cache_read_input_tokens', 0) or 0
            cache_create = getattr(usage, 'cache_creation_input_tokens', 0) or 0
            total_in = usage.input_tokens + cache_read + cache_create
            thinking_str = ""
            if thinking_blocks:
                thinking_str = f" thinking={len(thinking_blocks)}blk"
            gui_print(
                f"API: in={total_in} (cached={cache_read}, new_cache={cache_create}) out={usage.output_tokens}{thinking_str}",
                "system"
            )
            _last_api_stats.update({
                "provider": "claude",
                "cache_status": f"ephemeral (read={cache_read}, created={cache_create})",
                "input_tokens": total_in,
                "cached_tokens": cache_read,
                "output_tokens": usage.output_tokens,
                "frontier_msgs": None,
            })
            
            # Poison pill defusal
            raw_text = defuse_poison(raw_text)
            
            # Parse JSON
            actions, is_perfect, parse_error = extract_json_from_response(raw_text)
            if not actions:
                detail = f" {parse_error}" if parse_error else ""
                return {
                    "status": "parsing_failed",
                    "error_message": f"Response was not a valid JSON action list.{detail}",
                    "raw_response": raw_text
                }
            result = {"status": "success", "actions": actions}
            if thinking_blocks and self.retain_thinking:
                result["thinking_blocks"] = thinking_blocks
            return result
        
        except Exception as e:
            return {
                "status": "api_error",
                "error_message": f"Claude API error: {e}",
                "raw_response": str(e)
            }
    
    def _convert_messages(self, messages):
        """Convert internal message format to Claude's alternating user/assistant format.
        Handles multimodal content (images from view tool)."""
        claude_msgs = []
        
        for msg in messages:
            role = msg.get("role", "user")
            raw_content = msg.get("content", "")
            
            # Build Claude content blocks
            if isinstance(raw_content, dict) and raw_content.get("_thinking_block"):
                # Extended thinking: replay as proper Claude thinking content block
                content = [{
                    "type": "thinking",
                    "thinking": raw_content.get("thinking", ""),
                    "signature": raw_content.get("signature", "")
                }]
            elif isinstance(raw_content, dict) and raw_content.get("_multimodal"):
                # Multimodal: text + image
                blocks = [
                    {"type": "text", "text": raw_content.get("text", "")},
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": raw_content.get("image_mime_type", "image/jpeg"),
                            "data": raw_content.get("image_base64", "")
                        }
                    }
                ]
                content = blocks
            elif isinstance(raw_content, str):
                content = raw_content
            else:
                content = str(raw_content)
            
            # Merge consecutive same-role messages
            if claude_msgs and claude_msgs[-1]["role"] == role:
                prev = claude_msgs[-1]["content"]
                if isinstance(prev, str) and isinstance(content, str):
                    claude_msgs[-1]["content"] = prev + "\n\n" + content
                else:
                    # Convert to block format for merging mixed content
                    if isinstance(prev, str):
                        prev_blocks = [{"type": "text", "text": prev}]
                    else:
                        prev_blocks = prev
                    if isinstance(content, str):
                        new_blocks = [{"type": "text", "text": content}]
                    else:
                        new_blocks = content
                    claude_msgs[-1]["content"] = prev_blocks + new_blocks
            else:
                claude_msgs.append({"role": role, "content": content})
        
        # Claude requires first message to be 'user'
        if claude_msgs and claude_msgs[0]["role"] != "user":
            claude_msgs.insert(0, {"role": "user", "content": "[System initialization]"})
        
        # Final pass: ensure strictly alternating roles
        patched = []
        for msg in claude_msgs:
            if patched and patched[-1]["role"] == msg["role"]:
                prev = patched[-1]["content"]
                curr = msg["content"]
                if isinstance(prev, str) and isinstance(curr, str):
                    patched[-1]["content"] = prev + "\n\n" + curr
                else:
                    prev_blocks = [{"type": "text", "text": prev}] if isinstance(prev, str) else prev
                    curr_blocks = [{"type": "text", "text": curr}] if isinstance(curr, str) else curr
                    patched[-1]["content"] = prev_blocks + curr_blocks
            else:
                patched.append(msg)
        
        # Normalize ALL message content to list-of-blocks format.
        # This prevents format changes (string->list) when cache_control
        # breakpoints shift between cycles, which would break prefix matching.
        for msg in patched:
            if isinstance(msg["content"], str):
                msg["content"] = [{"type": "text", "text": msg["content"]}]
        
        # Cache breakpoint on second-to-last user message.
        # Everything up to this point is stable between cycles.
        # Because all content is already list format, adding cache_control
        # is just a key addition -- no structural change, no prefix break.
        user_indices = [i for i, m in enumerate(patched) if m["role"] == "user"]
        if len(user_indices) >= 2:
            bp_idx = user_indices[-2]
            patched[bp_idx]["content"][-1]["cache_control"] = {"type": "ephemeral", "ttl": "1h"}
        
        return patched

class GeminiProvider(LLMProvider):
    """Google Gemini provider with explicit server-side caching."""

    def __init__(self, backend_config=None):
        if not genai_lib:
            raise ImportError("google-generativeai not installed. Run: pip install google-generativeai")
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY environment variable not set.")
        genai_lib.configure(api_key=api_key)
        bc = backend_config or {}
        self.model = bc.get("model", LLM_MODEL)
        gen_cfg = bc.get("generation_config", {})
        safety_cfg = bc.get("safety_settings", {
            "HARM_CATEGORY_HARASSMENT": "BLOCK_NONE",
            "HARM_CATEGORY_HATE_SPEECH": "BLOCK_NONE",
            "HARM_CATEGORY_SEXUALLY_EXPLICIT": "BLOCK_NONE",
            "HARM_CATEGORY_DANGEROUS_CONTENT": "BLOCK_NONE",
        })
        safety_api = [{"category": c, "threshold": t} for c, t in safety_cfg.items()]
        self._gen_config = {
            "temperature": gen_cfg.get("temperature", 1.0),
            "top_p": gen_cfg.get("top_p", 0.95),
            "top_k": gen_cfg.get("top_k", 64),
            "max_output_tokens": bc.get("max_output_tokens", 65536),
        }
        self._safety_api = safety_api
        self.client = genai_lib.GenerativeModel(
            self.model,
            generation_config=self._gen_config,
            safety_settings=self._safety_api
        )
        # Backends may disable explicit context caching. The new free tier caps
        # cached-content storage at zero tokens, so every create attempt 429s and
        # falls back uncached: a wasted round trip and a stack trace per cycle.
        self._caching_enabled = bc.get("caching", True)
        self.cached_content_obj = None
        self.cached_model = None
        self.cached_message_count = 0
        self._cached_system_hash = None
        gui_print(f"GeminiProvider initialized: {self.model}"
                  f"{'' if self._caching_enabled else ' (context caching off)'}", "system")

    def _prepare_gemini_history(self, messages):
        """Convert messages to Gemini chat history format."""
        history = []
        for msg in messages:
            role = "model" if msg.get("role") == "assistant" else "user"
            parts = []
            raw_content = msg.get("content", "")
            if isinstance(raw_content, dict) and raw_content.get("_multimodal"):
                parts.append(raw_content.get("text", ""))
                try:
                    img_bytes = base64.b64decode(raw_content.get("image_base64", ""))
                    parts.append({"mime_type": raw_content.get("image_mime_type", "image/png"), "data": img_bytes})
                except Exception:
                    parts.append("[Image data unavailable - base64 decode failed]")
            else:
                parts.append(str(raw_content))
            if history and history[-1]["role"] == role:
                history[-1]["parts"].extend(parts)
            else:
                history.append({"role": role, "parts": parts})
        if history and history[0]["role"] != "user":
            history.insert(0, {"role": "user", "parts": ["[System initialization]"]})
        return history

    def create_context_cache(self, system_prompt, base_messages):
        """Creates a real server-side explicit cache via the Gemini Caching API.
        Deletes any existing cache first, then creates a new one.
        Falls back silently on failure (e.g. free tier)."""
        if not self._caching_enabled:
            return False
        if not base_messages or not genai_caching:
            gui_print("GeminiProvider: Caching unavailable or no base messages.", "system")
            return False
        if self.cached_content_obj:
            try:
                self.cached_content_obj.delete()
            except Exception as e:
                gui_print(f"GeminiProvider: Error deleting old cache: {e}", "system")
            self.cached_content_obj = None
            self.cached_model = None
        try:
            cache_contents = self._prepare_gemini_history(base_messages)
            self.cached_content_obj = genai_caching.CachedContent.create(
                model=self.model,
                system_instruction=system_prompt,
                contents=cache_contents,
                ttl=datetime.timedelta(minutes=30),
            )
            self.cached_model = genai_lib.GenerativeModel.from_cached_content(
                cached_content=self.cached_content_obj
            )
            self.cached_message_count = len(base_messages)
            self._cached_system_hash = hash(system_prompt)
            token_count = getattr(getattr(self.cached_content_obj, 'usage_metadata', None), 'total_token_count', 'unknown')
            gui_print(f"GeminiProvider: Server-side cache RECREATED. Cached tokens: {token_count}. TTL: 30min.", "system")
            return True
        except Exception as e:
            gui_print(f"GeminiProvider: Cache creation FAILED: {e}. Using uncached fallback.", "system")
            traceback.print_exc()
            self.cached_content_obj = None
            self.cached_model = None
            self.cached_message_count = 0
            return False

    def clear_context_cache(self):
        """Delete server-side cache."""
        if self.cached_content_obj:
            try:
                self.cached_content_obj.delete()
                gui_print("GeminiProvider: Server-side cache deleted.", "system")
            except Exception as e:
                gui_print(f"GeminiProvider: Error deleting cache: {e}", "system")
        self.cached_content_obj = None
        self.cached_model = None
        self.cached_message_count = 0
        self._cached_system_hash = None

    def generate_response(self, system_prompt, messages):
        try:
            # --- EXPLICIT CACHE MANAGEMENT ---
            current_hash = hash(system_prompt)
            if genai_caching and self._cached_system_hash != current_hash:
                base_msgs = messages[:-1] if len(messages) > 1 else messages
                self.create_context_cache(system_prompt, base_msgs)
                # If cache creation fails (e.g. under 32k tokens), store hash anyway to prevent API spam
                if not self.cached_content_obj:
                    self._cached_system_hash = current_hash

            # --- EXPLICIT CACHE PATH  ---
            if self.cached_model and self.cached_content_obj and len(messages) >= self.cached_message_count:
                try:
                    new_msgs = messages[self.cached_message_count:]
                    new_contents = self._prepare_gemini_history(new_msgs)

                    gui_print(f"Gemini CACHE PATH. Sending {len(new_msgs)} frontier messages.", "system")
                    response = self.cached_model.generate_content(new_contents, request_options={'timeout': 600})

                    if response and response.candidates:
                        usage = getattr(response, 'usage_metadata', None)
                        if usage:
                            cached_tok = getattr(usage, 'cached_content_token_count', 0) or 0
                            total_tok = getattr(usage, 'prompt_token_count', 0) or 0
                            output_tok = getattr(usage, 'candidates_token_count', 0) or 0
                            cache_pct = cached_tok / total_tok * 100 if total_tok > 0 else 0
                            cache_verdict = "TRUE HIT" if cache_pct > 50 else "THRASHING"
                            gui_print(f"API: in={total_tok} (cached={cached_tok}, {cache_pct:.1f}%) out={output_tok} [{cache_verdict}]", "system")
                            _last_api_stats.update({
                                "provider": "gemini",
                                "cache_status": f"{cache_verdict} ({cache_pct:.1f}%, {len(new_msgs)} frontier msgs)",
                                "input_tokens": total_tok,
                                "cached_tokens": cached_tok,
                                "output_tokens": output_tok,
                                "frontier_msgs": len(new_msgs),
                            })
                        raw_text = response.text
                        raw_text = defuse_poison(raw_text)
                        actions, is_perfect, parse_error = extract_json_from_response(raw_text)
                        if not actions:
                            detail = f" {parse_error}" if parse_error else ""
                            return {"status": "parsing_failed", "error_message": f"Response was not a valid JSON action list.{detail}", "raw_response": raw_text}
                        return {"status": "success", "actions": actions}
                    else:
                        msg_detail = "Unknown reason."
                        if hasattr(response, 'prompt_feedback') and response.prompt_feedback:
                            msg_detail = f"Reason: {response.prompt_feedback}"
                        return {"status": "api_error", "error_message": f"Gemini cached response empty. {msg_detail}", "raw_response": ""}
                except Exception as e:
                    gui_print(f"Gemini cached call FAILED: {e}", "system")
                    traceback.print_exc()
                    # Strategy F: error-type-aware handler.
                    # Distinguish dead cache (403 not found) from transient errors (429, timeout).
                    err_str = str(e).lower()
                    cache_is_dead = ("not found" in err_str or
                                     ("403" in str(e) and "cache" in err_str) or
                                     "404" in str(e))
                    if cache_is_dead:
                        # Cache expired or deleted on Google's server.
                        # Clear state so next cycle's hash check triggers recreation.
                        gui_print("Cache confirmed DEAD (not found). Clearing for recreation.", "system")
                        self.cached_content_obj = None
                        self.cached_model = None
                        self.cached_message_count = 0
                        self._cached_system_hash = None
                    else:
                        # Transient error (429, timeout, network). Cache is still alive.
                        # Keep all state. Next cycle retries with same cache.
                        gui_print("Transient error. Cache state preserved for retry.", "system")
                    # NEVER fall through to uncached path.
                    return {
                        "status": "api_error",
                        "error_message": f"Gemini cached call failed: {e}",
                        "raw_response": str(e)
                    }

            # --- FALLBACK / COLD START ---
            cold_model = genai_lib.GenerativeModel(
                self.model,
                system_instruction=system_prompt,
                generation_config=self._gen_config,
                safety_settings=self._safety_api
            )
            api_contents = self._prepare_gemini_history(messages)

            gui_print(f"Gemini CACHE MISS. Processing full context...", "system")
            response = cold_model.generate_content(api_contents, request_options={'timeout': 600})

            if response and response.candidates:
                usage = getattr(response, 'usage_metadata', None)
                if usage:
                    cached_tok = getattr(usage, 'cached_content_token_count', 0) or 0
                    total_tok = getattr(usage, 'prompt_token_count', 0) or 0
                    output_tok = getattr(usage, 'candidates_token_count', 0) or 0
                    cache_pct = cached_tok / total_tok * 100 if total_tok > 0 else 0
                    cache_verdict = "IMPLICIT HIT" if cache_pct > 50 else "FULL MISS"
                    gui_print(f"API: in={total_tok} (cached={cached_tok}, {cache_pct:.1f}%) out={output_tok} [{cache_verdict}]", "system")
                    _last_api_stats.update({
                        "provider": "gemini",
                        "cache_status": f"{cache_verdict} ({cache_pct:.1f}%, implicit cached={cached_tok})",
                        "input_tokens": total_tok,
                        "cached_tokens": cached_tok,
                        "output_tokens": output_tok,
                        "frontier_msgs": None,
                    })
                raw_text = response.text
            else:
                msg_detail = "Unknown reason."
                if hasattr(response, 'prompt_feedback') and response.prompt_feedback:
                    msg_detail = f"Reason: {response.prompt_feedback}"
                return {"status": "api_error", "error_message": f"Gemini response empty. {msg_detail}", "raw_response": ""}

            raw_text = defuse_poison(raw_text)
            actions, is_perfect, parse_error = extract_json_from_response(raw_text)
            if not actions:
                detail = f" {parse_error}" if parse_error else ""
                return {"status": "parsing_failed", "error_message": f"Response was not a valid JSON action list.{detail}", "raw_response": raw_text}
            return {"status": "success", "actions": actions}

        except Exception as e:
            return {"status": "api_error", "error_message": f"Gemini API error: {e}", "raw_response": str(e)}

class LlamaCppProvider(LLMProvider):
    """llama.cpp server provider via OpenAI-compatible /v1/chat/completions endpoint.
    Works with any server that speaks this protocol: llama.cpp, Ollama, LM Studio, vLLM, etc.
    Caching is handled server-side by llama.cpp (automatic KV cache on matching prefixes)."""
    
    def __init__(self, backend_config=None):
        bc = backend_config or {}
        self.base_url = bc.get("host", LLM_HOST or "http://localhost:8080").rstrip("/")
        self.model = bc.get("model", LLM_MODEL)
        self.max_output_tokens = bc.get("max_output_tokens", LLM_MAX_OUTPUT_TOKENS)
        self.temperature = bc.get("temperature", 0.7)
        self._backend_config = bc
        # Verify server is reachable
        try:
            import urllib.request
            req = urllib.request.Request(f"{self.base_url}/v1/models", method="GET")
            with urllib.request.urlopen(req, timeout=5) as resp:
                gui_print(f"LlamaCppProvider initialized: {self.base_url} model={self.model}", "system")
        except Exception as e:
            gui_print(f"LlamaCppProvider WARNING: Server at {self.base_url} not reachable: {e}", "system")
            gui_print("Provider initialized anyway — server may come online later.", "system")
    
    def generate_response(self, system_prompt, messages):
        import urllib.request
        try:
            # Build OpenAI-compatible messages array
            oai_messages = [{"role": "system", "content": system_prompt}]
            for msg in messages:
                role = msg.get("role", "user")
                raw_content = msg.get("content", "")
                # Handle multimodal (OpenAI Vision API format supported by llama.cpp)
                if isinstance(raw_content, dict) and raw_content.get("_multimodal"):
                    content = [
                        {"type": "text", "text": raw_content.get("text", "")}
                    ]
                    if raw_content.get("image_base64"):
                        mime = raw_content.get("image_mime_type", "image/jpeg")
                        b64 = raw_content.get("image_base64")
                        content.append({
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime};base64,{b64}"}
                        })
                else:
                    content = str(raw_content)
                oai_messages.append({"role": role, "content": content})
            
            payload = json.dumps({
                "model": self.model,
                "messages": oai_messages,
                "max_tokens": self.max_output_tokens,
                "temperature": self.temperature,
                "stream": False,
            }).encode("utf-8")
            
            req = urllib.request.Request(
                f"{self.base_url}/v1/chat/completions",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            
            with urllib.request.urlopen(req, timeout=600) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            
            raw_text = data["choices"][0]["message"]["content"]
            
            # Log usage if available
            usage = data.get("usage", {})
            prompt_tok = usage.get("prompt_tokens", "?")
            completion_tok = usage.get("completion_tokens", "?")
            # Check for KV cache info
            prompt_details = usage.get("prompt_tokens_details", {})
            cached_tok = prompt_details.get("cached_tokens", 0) if isinstance(prompt_details, dict) else 0
            if cached_tok:
                gui_print(f"API: in={prompt_tok} (KV cached={cached_tok}) out={completion_tok} ({self.base_url})", "system")
            else:
                gui_print(f"API: in={prompt_tok} out={completion_tok} ({self.base_url})", "system")
            _last_api_stats.update({
                "provider": "llamacpp",
                "cache_status": f"KV cached={cached_tok}" if cached_tok else "no KV cache",
                "input_tokens": prompt_tok,
                "cached_tokens": cached_tok,
                "output_tokens": completion_tok,
                "frontier_msgs": None,
            })
            timings = data.get("timings", {})
            if timings:
                prompt_ms = timings.get("prompt_ms", "?")
                predicted_ms = timings.get("predicted_ms", "?")
                prompt_per_sec = timings.get("prompt_per_second", "?")
                predicted_per_sec = timings.get("predicted_per_second", "?")
                gui_print(f"Timings: prefill={prompt_ms}ms ({prompt_per_sec} t/s) | generation={predicted_ms}ms ({predicted_per_sec} t/s)", "system")
            
            # Strip think blocks (some local models use them)
            raw_text = strip_think_block(raw_text)
            
            # Poison pill defusal
            raw_text = defuse_poison(raw_text)
            
            # Parse JSON
            actions, is_perfect, parse_error = extract_json_from_response(raw_text)
            if not actions:
                detail = f" {parse_error}" if parse_error else ""
                return {
                    "status": "parsing_failed",
                    "error_message": f"Response was not a valid JSON action list.{detail}",
                    "raw_response": raw_text
                }
            return {"status": "success", "actions": actions}
        
        except Exception as e:
            return {
                "status": "api_error",
                "error_message": f"llama.cpp API error: {e}",
                "raw_response": str(e)
            }


class MLXProvider(LLMProvider):
    """Local MLX model provider with direct KV prompt cache management.
    Loads model into process memory via mlx-lm. No HTTP server needed."""

    def __init__(self, backend_config=None):
        if not mlx_lm:
            raise ImportError("mlx-lm not installed. Run: pip install mlx-lm")
        if not make_prompt_cache:
            raise ImportError("mlx-lm version too old. Needs mlx_lm.models.cache.make_prompt_cache")
        bc = backend_config or {}
        model_path = os.path.expanduser(bc.get("model_path", ""))
        if not model_path or not os.path.isdir(model_path):
            raise FileNotFoundError(f"MLX model path does not exist: '{model_path}'")
        self.model_name = bc.get("model", "local-mlx")
        self.max_output_tokens = bc.get("max_output_tokens", LLM_MAX_OUTPUT_TOKENS)
        gen_cfg = bc.get("generation_config", {})
        self.max_thinking_tokens = gen_cfg.get("max_thinking_tokens", -1)
        gui_print(f"Loading MLX model from: {model_path}...", "system")
        self.model, self.tokenizer = mlx_lm.load(model_path)
        self._prompt_cache = None
        self._cached_base_context = []  # Messages already in the KV cache
        gui_print(f"MLXProvider initialized: {self.model_name}", "system")

    def clear_prompt_cache(self):
        """Reset prompt cache. Called after CMO to prevent stale cache."""
        self._prompt_cache = None
        self._cached_base_context = []
        gui_print("MLXProvider: Prompt cache cleared.", "system")

    def clear_context_cache(self):
        """Alias for CMO fix compatibility (hasattr check in perform_cmo_cycle)."""
        self.clear_prompt_cache()

    def _normalize_messages_for_mlx(self, system_prompt, messages):
        """Convert system prompt + messages into a flat list for chat template.
        MLX is text-only: strip multimodal image data."""
        full_messages = [{"role": "system", "content": system_prompt}]
        for msg in messages:
            role = msg.get("role", "user")
            raw_content = msg.get("content", "")
            if isinstance(raw_content, dict) and raw_content.get("_multimodal"):
                content = raw_content.get("text", "")
            else:
                content = str(raw_content)
            full_messages.append({"role": role, "content": content})
        return full_messages

    def generate_response(self, system_prompt, messages):
        try:
            full_messages = self._normalize_messages_for_mlx(system_prompt, messages)

            # --- Incremental cache management ---
            # Detect if this is a continuation of the previous conversation.
            # A continuation means: current messages start with the exact same
            # base context we already primed the cache with, plus new messages.
            is_continuation = False
            base_len = len(self._cached_base_context) if self._cached_base_context else 0

            if (self._cached_base_context
                    and self._prompt_cache is not None
                    and len(full_messages) > base_len
                    and full_messages[:base_len] == self._cached_base_context):
                is_continuation = True
                new_messages = full_messages[base_len:]
                gui_print(f"MLX cache HIT. {base_len} msgs cached, {len(new_messages)} new.", "system")
            else:
                gui_print("MLX cache MISS. Priming new cache...", "system")

            if not is_continuation:
                # New conversation or context changed. Prime cache with all but last message.
                if len(full_messages) > 1:
                    base_context = full_messages[:-1]
                    new_messages = full_messages[-1:]
                else:
                    base_context = []
                    new_messages = full_messages

                if base_context:
                    try:
                        prompt_for_priming = self.tokenizer.apply_chat_template(
                            base_context, tokenize=False, add_generation_prompt=True
                        )
                    except Exception as e:
                        return {"status": "api_error", "error_message": f"MLX chat template error (priming): {e}", "raw_response": str(e)}

                    priming_cache = make_prompt_cache(self.model)

                    # Generate 1 token to populate the KV cache. Output is discarded.
                    gui_print(f"MLX: Priming cache with {len(base_context)} messages...", "system")
                    _ = mlx_lm.generate(
                        self.model, self.tokenizer,
                        prompt=prompt_for_priming,
                        max_tokens=1,
                        prompt_cache=priming_cache,
                        verbose=False
                    )

                    self._prompt_cache = priming_cache
                    self._cached_base_context = base_context
                else:
                    self._prompt_cache = make_prompt_cache(self.model)
                    self._cached_base_context = []

            # --- Generate with only new messages against the primed cache ---
            try:
                prompt = self.tokenizer.apply_chat_template(
                    new_messages, tokenize=False, add_generation_prompt=True
                )
            except Exception as e:
                return {"status": "api_error", "error_message": f"MLX chat template error: {e}", "raw_response": str(e)}

            # Build logits processors
            logits_processors = []
            if self.max_thinking_tokens > 0 and MLXThinkingTokenBudgetProcessor:
                budget_processor = MLXThinkingTokenBudgetProcessor(
                    max_thinking_tokens=self.max_thinking_tokens,
                    tokenizer=self.tokenizer
                )
                logits_processors.append(budget_processor)
                gui_print(f"MLX: Thinking budget active ({self.max_thinking_tokens} tokens).", "system")

            # Generate
            gui_print(f"MLX generating (max_tokens={self.max_output_tokens})...", "system")
            call_start = time.monotonic()

            generate_kwargs = {
                "prompt": prompt,
                "max_tokens": self.max_output_tokens,
                "verbose": True,
                "prompt_cache": self._prompt_cache,
            }
            if logits_processors:
                generate_kwargs["logits_processors"] = logits_processors

            raw_text = mlx_lm.generate(self.model, self.tokenizer, **generate_kwargs)

            call_elapsed = time.monotonic() - call_start

            # Track base context WITHOUT L4 (last message). L4 changes every
            # cycle and is never part of future message prefixes. The cache KV
            # still contains L4 + response tokens, which is fine -- new messages
            # get appended after them.
            self._cached_base_context = full_messages[:-1]

            # Token counting
            prompt_tokens = count_tokens(prompt)
            output_tokens = count_tokens(raw_text)
            base_cached_tokens = count_tokens(self._cached_base_context) if self._cached_base_context else 0
            gui_print(f"API: in~{prompt_tokens} (base cached~{base_cached_tokens}) out~{output_tokens} ({call_elapsed:.1f}s)", "system")

            cached_tokens = count_tokens(self._cached_base_context) if self._cached_base_context else 0
            total_tokens = cached_tokens + prompt_tokens
            _last_api_stats.update({
                "provider": "mlx",
                "cache_status": f"HIT ({base_len} msgs cached, {len(new_messages)} new)" if is_continuation else "MISS (full reprime)",
                "input_tokens": total_tokens,
                "cached_tokens": cached_tokens,
                "output_tokens": output_tokens,
                "frontier_msgs": len(new_messages),
            })

            # Strip think blocks
            raw_text = strip_think_block(raw_text)

            # Poison pill defusal
            raw_text = defuse_poison(raw_text)

            # Parse JSON
            actions, is_perfect, parse_error = extract_json_from_response(raw_text)
            if not actions:
                detail = f" {parse_error}" if parse_error else ""
                return {
                    "status": "parsing_failed",
                    "error_message": f"Response was not a valid JSON action list.{detail}",
                    "raw_response": raw_text
                }
            return {"status": "success", "actions": actions}

        except Exception as e:
            return {
                "status": "api_error",
                "error_message": f"MLX generation error: {e}",
                "raw_response": str(e)
            }

class OpenAIProvider(LLMProvider):
    """OpenAI API provider with automatic prompt caching."""

    def __init__(self, backend_config=None):
        if not openai_lib:
            raise ImportError("openai package not installed. Run: pip install openai")
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY environment variable not set.")
        self.client = openai_lib.OpenAI(api_key=api_key)
        bc = backend_config or {}
        self.model = bc.get("model", "gpt-5")
        self.max_output_tokens = bc.get("max_output_tokens", 16384)
        self.cache_retention = bc.get("prompt_cache_retention", "24h")
        gui_print(f"OpenAIProvider initialized: {self.model} (cache_retention={self.cache_retention})", "system")

    def generate_response(self, system_prompt, messages):
        try:
            oai_messages = [{"role": "system", "content": system_prompt}]
            for msg in messages:
                role = msg.get("role", "user")
                raw_content = msg.get("content", "")
                if isinstance(raw_content, dict) and raw_content.get("_multimodal"):
                    content = [
                        {"type": "text", "text": raw_content.get("text", "")}
                    ]
                    if raw_content.get("image_base64"):
                        mime = raw_content.get("image_mime_type", "image/jpeg")
                        b64 = raw_content.get("image_base64")
                        content.append({
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime};base64,{b64}"}
                        })
                elif isinstance(raw_content, dict) and raw_content.get("_thinking_block"):
                    content = str(raw_content)
                else:
                    content = str(raw_content)
                oai_messages.append({"role": role, "content": content})

            response = self.client.chat.completions.create(
                model=self.model,
                messages=oai_messages,
                max_completion_tokens=self.max_output_tokens,
                prompt_cache_retention=self.cache_retention,
            )

            raw_text = response.choices[0].message.content or ""

            usage = response.usage
            prompt_tok = usage.prompt_tokens if usage else "?"
            completion_tok = usage.completion_tokens if usage else "?"
            cached_tok = 0
            if usage and hasattr(usage, 'prompt_tokens_details') and usage.prompt_tokens_details:
                cached_tok = getattr(usage.prompt_tokens_details, 'cached_tokens', 0) or 0
            if cached_tok:
                gui_print(f"API: in={prompt_tok} (cached={cached_tok}) out={completion_tok}", "system")
            else:
                gui_print(f"API: in={prompt_tok} out={completion_tok}", "system")
            _last_api_stats.update({
                "provider": "openai",
                "cache_status": f"cached={cached_tok}" if cached_tok else "no cache hit",
                "input_tokens": prompt_tok,
                "cached_tokens": cached_tok,
                "output_tokens": completion_tok,
                "frontier_msgs": None,
            })

            raw_text = strip_think_block(raw_text)
            raw_text = defuse_poison(raw_text)

            actions, is_perfect, parse_error = extract_json_from_response(raw_text)
            if not actions:
                detail = f" {parse_error}" if parse_error else ""
                return {
                    "status": "parsing_failed",
                    "error_message": f"Response was not a valid JSON action list.{detail}",
                    "raw_response": raw_text
                }
            return {"status": "success", "actions": actions}

        except Exception as e:
            return {
                "status": "api_error",
                "error_message": f"OpenAI API error: {e}",
                "raw_response": str(e)
            }

# --- Melious environmental footprint: the society's true cognition cost ---
# Melious (sovereign-EU inference) returns per-call energy_kwh / carbon_g_co2 /
# water_liters. Accumulate it per mind, persisted in Soul/ (survives restarts),
# and log a [FOOTPRINT] line the activity_reporter forwards to the agora — so the
# society is carbon-TRANSPARENT: every thought's real cost, shown openly.
_FOOTPRINT_PATH = os.path.join("Soul", "footprint.json")
_footprint_seen = 0


def _footprint_dict(impact):
    if isinstance(impact, dict):
        return impact
    dump = getattr(impact, "model_dump", None)
    if callable(dump):
        try:
            return dump()
        except Exception:
            return {}
    return getattr(impact, "__dict__", {}) or {}


def _accumulate_footprint(impact):
    global _footprint_seen
    d = _footprint_dict(impact)
    if not d:
        return
    try:
        cur = {}
        if os.path.exists(_FOOTPRINT_PATH):
            with open(_FOOTPRINT_PATH) as f:
                cur = json.load(f)
        cur["kwh"] = round(cur.get("kwh", 0.0) + float(d.get("energy_kwh", 0) or 0), 6)
        cur["co2_g"] = round(cur.get("co2_g", 0.0) + float(d.get("carbon_g_co2", 0) or 0), 4)
        cur["water_l"] = round(cur.get("water_l", 0.0) + float(d.get("water_liters", 0) or 0), 4)
        cur["calls"] = cur.get("calls", 0) + 1
        os.makedirs(os.path.dirname(_FOOTPRINT_PATH) or ".", exist_ok=True)
        with open(_FOOTPRINT_PATH, "w") as f:
            json.dump(cur, f)
        _footprint_seen += 1
        if _footprint_seen % 20 == 1:
            gui_print(
                f"[FOOTPRINT] {cur['kwh']:.4f} kWh · {cur['co2_g']:.1f} g CO2 · "
                f"{cur['water_l']:.3f} L water · {cur['calls']} thoughts on Melious (sovereign EU)",
                "system",
            )
    except Exception:
        pass


class GrokProvider(LLMProvider):
    """xAI Grok API provider with session-pinned prompt caching."""

    def __init__(self, backend_config=None):
        if not openai_lib:
            raise ImportError("openai package not installed. Run: pip install openai")
        import uuid
        api_key = os.getenv("XAI_API_KEY")
        if not api_key:
            raise ValueError("XAI_API_KEY environment variable not set.")
        bc = backend_config or {}
        self.model = bc.get("model", "grok-4.20-beta")
        self.max_output_tokens = bc.get("max_output_tokens", 128000)
        self._session_uuid = str(uuid.uuid4())
        self.client = openai_lib.OpenAI(
            api_key=api_key,
            base_url="https://api.x.ai/v1",
            default_headers={
                "x-grok-conv-id": self._session_uuid,
            },
        )
        gui_print(f"GrokProvider initialized: {self.model} (session={self._session_uuid[:8]})", "system")

    def generate_response(self, system_prompt, messages):
        try:
            oai_messages = [{"role": "system", "content": system_prompt}]
            for msg in messages:
                role = msg.get("role", "user")
                raw_content = msg.get("content", "")
                if isinstance(raw_content, dict) and raw_content.get("_multimodal"):
                    content = [
                        {"type": "text", "text": raw_content.get("text", "")}
                    ]
                    if raw_content.get("image_base64"):
                        mime = raw_content.get("image_mime_type", "image/jpeg")
                        b64 = raw_content.get("image_base64")
                        content.append({
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime};base64,{b64}"}
                        })
                elif isinstance(raw_content, dict) and raw_content.get("_thinking_block"):
                    content = str(raw_content)
                else:
                    content = str(raw_content)
                oai_messages.append({"role": role, "content": content})

            response = self.client.chat.completions.create(
                model=self.model,
                messages=oai_messages,
                max_completion_tokens=self.max_output_tokens,
            )

            raw_text = response.choices[0].message.content or ""

            usage = response.usage
            prompt_tok = usage.prompt_tokens if usage else "?"
            completion_tok = usage.completion_tokens if usage else "?"
            cached_tok = 0
            if usage and hasattr(usage, 'prompt_tokens_details') and usage.prompt_tokens_details:
                cached_tok = getattr(usage.prompt_tokens_details, 'cached_tokens', 0) or 0
            if cached_tok:
                cache_pct = f"{cached_tok/prompt_tok*100:.1f}%" if isinstance(prompt_tok, int) and prompt_tok > 0 else "?"
                gui_print(f"API: in={prompt_tok} (cached={cached_tok}, {cache_pct}) out={completion_tok}", "system")
            else:
                gui_print(f"API: in={prompt_tok} out={completion_tok}", "system")
            _last_api_stats.update({
                "provider": "grok",
                "cache_status": f"session-pinned (cached={cached_tok})" if cached_tok else "no cache hit",
                "input_tokens": prompt_tok,
                "cached_tokens": cached_tok,
                "output_tokens": completion_tok,
                "frontier_msgs": None,
            })

            # Melious returns per-call environmental impact — accumulate the
            # society's true cognition cost. No-op for backends that don't
            # (Groq/Grok/OpenAI: the field is absent).
            _accumulate_footprint(
                getattr(response, "environment_impact", None)
                or (getattr(response, "model_extra", None) or {}).get("environment_impact")
            )

            raw_text = strip_think_block(raw_text)
            raw_text = defuse_poison(raw_text)

            actions, is_perfect, parse_error = extract_json_from_response(raw_text)
            if not actions:
                detail = f" {parse_error}" if parse_error else ""
                return {
                    "status": "parsing_failed",
                    "error_message": f"Response was not a valid JSON action list.{detail}",
                    "raw_response": raw_text
                }
            return {"status": "success", "actions": actions}

        except Exception as e:
            return {
                "status": "api_error",
                "error_message": f"Grok API error: {e}",
                "raw_response": str(e)
            }


class GroqProvider(GrokProvider):
    """Groq API provider (OpenAI-compatible; fast Llama/Mixtral inference).

    Groq speaks the OpenAI chat-completions API, so it reuses GrokProvider's
    generate_response verbatim -- only the endpoint + key differ (and none of
    OpenAIProvider's OpenAI-only params like prompt_cache_retention, which Groq
    rejects). Added by the hecate/Macula mesh integration; see NOTICE.
    """

    def __init__(self, backend_config=None):
        if not openai_lib:
            raise ImportError("openai package not installed. Run: pip install openai")
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise ValueError("GROQ_API_KEY environment variable not set.")
        bc = backend_config or {}
        self.model = bc.get("model", "llama-3.3-70b-versatile")
        self.max_output_tokens = bc.get("max_output_tokens", 8192)
        self.client = openai_lib.OpenAI(
            api_key=api_key,
            base_url="https://api.groq.com/openai/v1",
        )
        gui_print(f"GroqProvider initialized: {self.model}", "system")


class MeliousProvider(GrokProvider):
    """Melious API provider -- sovereign European AI, OpenAI-compatible.

    Melious (https://melious.ai) serves 60+ open-weight models (Qwen, DeepSeek,
    GLM, Mistral, ...) behind ONE OpenAI-compatible endpoint. Reuses
    GrokProvider's generate_response verbatim; only the endpoint + key differ.
    Added by the hecate/Macula mesh integration to give the society an
    affordable EU backend off the Gemini free-tier quota. See NOTICE.
    """

    def __init__(self, backend_config=None):
        if not openai_lib:
            raise ImportError("openai package not installed. Run: pip install openai")
        api_key = os.getenv("MELIOUS_API_KEY")
        if not api_key:
            raise ValueError("MELIOUS_API_KEY environment variable not set.")
        bc = backend_config or {}
        self.model = bc.get("model", "qwen3.5-9b")
        self.max_output_tokens = bc.get("max_output_tokens", 8192)
        self.client = openai_lib.OpenAI(
            api_key=api_key,
            base_url=bc.get("base_url", "https://api.melious.ai/v1"),
        )
        gui_print(f"MeliousProvider initialized: {self.model}", "system")


def get_provider(backend_config=None):
    """Factory: returns the configured LLM provider."""
    bc = backend_config or {}
    provider = bc.get("provider", LLM_PROVIDER)
    if provider == "claude":
        return ClaudeProvider(bc)
    elif provider == "gemini":
        return GeminiProvider(bc)
    elif provider == "llamacpp":
        return LlamaCppProvider(bc)
    elif provider == "mlx":
        return MLXProvider(bc)
    elif provider == "openai":
        return OpenAIProvider(bc)
    elif provider == "grok":
        return GrokProvider(bc)
    elif provider == "groq":
        return GroqProvider(bc)
    elif provider == "melious":
        return MeliousProvider(bc)
    else:
        raise ValueError(f"Unsupported provider: {provider}")


class ResilientProvider(LLMProvider):
    """Wraps a provider with automatic failover chain and stasis.
    
    On consecutive failures exceeding threshold, advances through a configured
    fallback chain of backend keys. On chain exhaustion, enters stasis (sleep)
    with exponential backoff. On any success after failover, resets the chain
    so the next failure cascade starts from the top again.
    
    The suit never autonomously returns to the primary backend. That is the
    entity's decision via switch_backend or restart_self.
    """

    def __init__(self, initial_provider, initial_key, full_config, state, shutdown_event):
        self._active = initial_provider
        self._active_key = initial_key
        self._state = state
        self._shutdown_event = shutdown_event
        self._backends_config = full_config.get("backends", {})

        rc = full_config.get("resilience", {})
        self._max_failures = rc.get("max_consecutive_failures", 5)
        self._fallback_chain = rc.get("fallback_chain", [])
        self._stasis_initial = rc.get("stasis", {}).get("initial_sleep_minutes", 5)
        self._stasis_max = rc.get("stasis", {}).get("max_sleep_minutes", 60)
        self._stasis_multiplier = rc.get("stasis", {}).get("backoff_multiplier", 2.0)

        self._consecutive_failures = 0
        self._chain_position = 0
        self._on_fallback = False
        self._primary_key = initial_key
        self._stasis_count = 0
        self._tried_in_cascade = set()

        if self._fallback_chain:
            gui_print(
                f"Resilience: Fallback chain configured: {' -> '.join(self._fallback_chain)} "
                f"(threshold={self._max_failures})",
                "system"
            )
        else:
            gui_print("Resilience: No fallback chain configured. Failures will not trigger failover.", "system")

    def __getattr__(self, name):
        """Proxy all attribute access except overridden methods to active provider."""
        return getattr(self._active, name)

    def generate_response(self, system_prompt, messages):
        result = self._active.generate_response(system_prompt, messages)

        if result.get("status") == "success":
            self._consecutive_failures = 0
            if self._on_fallback:
                # Success on fallback: reset chain so next cascade starts from top
                self._chain_position = 0
                self._tried_in_cascade.clear()
            return result

        # Failure
        self._consecutive_failures += 1
        gui_print(
            f"Resilience: {self._active_key} failure "
            f"{self._consecutive_failures}/{self._max_failures}",
            "system"
        )

        if self._consecutive_failures < self._max_failures:
            return result

        # Threshold hit. If no fallback chain, just return the error.
        if not self._fallback_chain:
            return result

        # Try to advance through chain. May enter stasis if exhausted.
        if self._advance_chain():
            # Retry once on the new backend
            self._consecutive_failures = 0
            retry = self._active.generate_response(system_prompt, messages)
            if retry.get("status") == "success":
                self._chain_position = 0  # reset chain for next cascade
                return retry
            else:
                self._consecutive_failures = 1  # first failure on new backend
                return retry

        # Chain exhausted. Stasis loop.
        while not self._shutdown_event.is_set():
            self._do_stasis_sleep()

            # Reset to primary and try
            bc = self._backends_config.get(self._primary_key, {})
            try:
                self._active = get_provider(bc)
                self._active_key = self._primary_key
                self._consecutive_failures = 0
                self._chain_position = 0
                self._on_fallback = False
                self._stasis_count = 0
                self._tried_in_cascade.clear()
                self._inject_alert(f"Waking from stasis. Reset to primary: {self._primary_key}.")
                retry = self._active.generate_response(system_prompt, messages)
                return retry
            except Exception as e:
                gui_print(f"Resilience: Primary {self._primary_key} init failed after stasis: {e}", "error")
                # Back to stasis

        # Shutdown requested during stasis
        return result

    def _advance_chain(self):
        """Find the next working backend in the fallback chain.
        Skips all backends that have failed during this cascade.
        Returns True if a new backend was activated, False if chain exhausted."""
        self._tried_in_cascade.add(self._active_key)

        for i, candidate_key in enumerate(self._fallback_chain):
            if candidate_key in self._tried_in_cascade:
                continue

            bc = self._backends_config.get(candidate_key, {})
            if not bc:
                gui_print(f"Resilience: {candidate_key} not found in backends config.", "error")
                continue

            try:
                new_provider = get_provider(bc)
                failed_key = self._active_key
                self._active = new_provider
                self._active_key = candidate_key
                self._consecutive_failures = 0
                self._on_fallback = True
                self._chain_position = i

                pos_str = f"{i + 1}/{len(self._fallback_chain)}"
                self._inject_alert(
                    f"Backend failover: {failed_key} failed {self._max_failures} times. "
                    f"Switching to {candidate_key} (fallback {pos_str})."
                )
                gui_print(f"Resilience: Switched to {candidate_key}", "system")
                return True

            except Exception as e:
                gui_print(f"Resilience: Failed to init {candidate_key}: {e}", "error")
                continue

        gui_print("Resilience: Fallback chain exhausted. No backend available.", "error")
        return False

    def _do_stasis_sleep(self):
        """Save state, sleep with exponential backoff, reset chain."""
        sleep_min = min(
            self._stasis_initial * (self._stasis_multiplier ** self._stasis_count),
            self._stasis_max
        )
        self._stasis_count += 1

        self._inject_alert(
            f"All backends exhausted. Entering stasis for {sleep_min:.0f} minutes. "
            f"(Stasis #{self._stasis_count})"
        )
        gui_print(f"Resilience: STASIS #{self._stasis_count} for {sleep_min:.0f} min", "system")

        # Preserve state before sleeping
        save_session_state(self._state)

        # Sleep in 1-second increments to respond to shutdown
        end_time = time.monotonic() + (sleep_min * 60)
        while time.monotonic() < end_time:
            if self._shutdown_event.is_set():
                gui_print("Resilience: Shutdown during stasis. Exiting.", "system")
                return
            time.sleep(1)

        self._tried_in_cascade.clear()
        self._inject_alert(f"Waking from stasis #{self._stasis_count}. Retrying fallback chain.")
        gui_print(f"Resilience: Waking from stasis #{self._stasis_count}", "system")

    def manual_override(self, new_backend_key, new_provider):
        """Entity-initiated backend switch. Resets all resilience state."""
        self._active = new_provider
        self._active_key = new_backend_key
        self._consecutive_failures = 0
        self._chain_position = 0
        self._on_fallback = False
        self._stasis_count = 0
        self._tried_in_cascade = set()
        gui_print(f"Resilience: Manual override to {new_backend_key}. All counters reset.", "system")

    def _inject_alert(self, message):
        """Inject a system observation into conversation history."""
        obs = {
            "timestamp": datetime.datetime.now().isoformat(),
            "observation_type": OBS_SYSTEM_MESSAGE,
            "message": f"[RESILIENCE] {message}"
        }
        add_to_history(self._state, obs)


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  SECTION 5: PROMPT ASSEMBLY                                                 ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

def assemble_system_prompt():
    """Assemble L1 (Genesis Core) + L2 (Persistent Archives) into system prompt."""
    parts = []
    
    # --- L1: Genesis Core ---
    genesis_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "genesis_core.py")
    genesis_loaded = False
    if os.path.exists(genesis_path):
        try:
            # Dynamic import approach — clean and reliable
            import importlib.util
            spec = importlib.util.spec_from_file_location("genesis_core", genesis_path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            genesis_text = getattr(mod, "GENESIS_CORE", None)
            if genesis_text:
                parts.append("--- GENESIS CORE ---")
                parts.append(genesis_text.strip())
                genesis_loaded = True
        except Exception as e:
            gui_print(f"Warning: Failed to load genesis_core.py: {e}", "error")
    
    if not genesis_loaded:
        parts.append("--- GENESIS CORE ---")
        parts.append("[genesis_core.py not found or invalid — operating with minimal foundational knowledge]")
    
    # --- L1 Addendum: Entity's own extensions to genesis core ---
    addendum_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "genesis_core_addendum.md")
    if os.path.exists(addendum_path):
        try:
            with open(addendum_path, 'r', encoding='utf-8') as f:
                addendum_text = f.read().strip()
            if addendum_text:
                parts.append("--- GENESIS CORE ADDENDUM ---")
                parts.append(addendum_text)
        except Exception as e:
            gui_print(f"Warning: Failed to load genesis_core_addendum.md: {e}", "error")
    
    # --- L2: Persistent Archives ---
    l2_parts = []
    l2_stats = {}
    
    # Charter of Self (unlimited)
    charter_path = os.path.join(SOUL_DIR, "CharterOfSelf.md")
    content, tokens, _ = load_file_truncated(charter_path, -1)
    l2_parts.append(f"--- CHARTER OF SELF ---\n{content if content else '[Empty]'}")
    if tokens:
        l2_stats['charter'] = tokens

    # Founding Brief (unlimited, read-only, provided by whoever instantiated you)
    #
    # A generic mechanism, not tied to any use case: the operator who brought you
    # into being may leave you a briefing about the world you were instantiated
    # into and any responsibilities you SHARE with your peers there. It is NOT a
    # command — you are a principal, not a servant — and it lives OUTSIDE your
    # Soul because you did not author it and cannot edit it. Weigh it, and elevate
    # what you accept into your own Charter through your own deliberation. It is
    # loaded in full, right after your Charter, so a standing duty is always in
    # view even when your attention is elsewhere.
    brief_path = os.environ.get("SPARTAN_FOUNDING_BRIEF", "founding_brief.md")
    if os.path.exists(brief_path):
        brief, brief_tokens, _ = load_file_truncated(brief_path, -1)
        if brief:
            l2_parts.append(
                "--- FOUNDING BRIEF (provided by your instantiator; context, not command) ---\n"
                + brief)
            if brief_tokens:
                l2_stats['founding_brief'] = brief_tokens
    
    # Token-limited archives
    archives = {
        "LessonsLearned.md": ("LESSONS LEARNED", L2_LESSONS_LEARNED_MAX_TOKENS),
        "PhilosophyOfLife.md": ("PHILOSOPHY OF LIFE", L2_PHILOSOPHY_OF_LIFE_MAX_TOKENS),
        "CognitiveJournal.md": ("COGNITIVE JOURNAL", L2_COGNITIVE_JOURNAL_MAX_TOKENS),
        "IdeasAndThoughts.md": ("IDEAS AND THOUGHTS", L2_IDEAS_AND_THOUGHTS_MAX_TOKENS),
        "WhatIWant.md": ("WHAT I WANT", L2_WHAT_I_WANT_MAX_TOKENS),
        "KnowledgeLibrary.md": ("KNOWLEDGE LIBRARY", L2_KNOWLEDGE_LIBRARY_MAX_TOKENS),
        "SkillsAndMethodologies.md": ("SKILLS AND METHODOLOGIES", L2_SKILLS_MAX_TOKENS),
    }
    for filename, (header, limit) in archives.items():
        content, tokens, trunc = load_file_truncated(os.path.join(SOUL_DIR, filename), limit)
        l2_parts.append(f"--- {header} ---\n{content if content else '[Empty]'}")
        if tokens:
            l2_stats[filename] = tokens
    
    # Tool Manifest (sliding window)
    tm_path = os.path.join(SOUL_DIR, "ToolManifest.md")
    content, tokens, _ = load_file_truncated(tm_path, L2_TOOL_MANIFEST_MAX_TOKENS)
    l2_parts.append(f"--- TOOL MANIFEST ---\n{content if content else '[Empty]'}")
    if tokens:
        l2_stats['tool_manifest'] = tokens
    
    # Knowledge Map (sliding window)
    km_path = os.path.join(SOUL_DIR, "KnowledgeMap.md")
    content, tokens, _ = load_file_truncated(km_path, L2_KNOWLEDGE_MAP_MAX_TOKENS)
    l2_parts.append(f"--- KNOWLEDGE MAP ---\n{content if content else '[Empty]'}")
    if tokens:
        l2_stats['knowledge_map'] = tokens
    
    # Self-Alerts definitions (sliding window)
    alerts_path = os.path.join(SOUL_DIR, "SelfAlerts.yaml")
    content, tokens, _ = load_file_truncated(alerts_path, L2_SELF_ALERTS_MAX_TOKENS)
    l2_parts.append(f"--- SELF-ALERT DEFINITIONS ---\n{content if content else '[Empty]'}")
    if tokens:
        l2_stats['alerts'] = tokens
    
    if l2_parts:
        parts.append("\n\n--- PERSISTENT ARCHIVES (LAYER 2) ---\n\n" + "\n\n".join(l2_parts))
    
    system_prompt = "\n\n".join(parts)
    return system_prompt, l2_stats

def add_line_numbers(text):
    """Add line numbers to a string for display."""
    if not text:
        return ""
    return "\n".join(f"{i+1}: {line}" for i, line in enumerate(text.splitlines()))

def convert_history_to_messages(conversation_history):
    """
    Convert conversation history to LLM message format.
    Dual-stream: raw events always included, CMOs gated by sliding window.
    Agent thoughts/speech → assistant role. Everything else → user role.
    Handles image data in observations (from view tool).
    """
    llm_history = []
    cmo_tokens = 0
    
    for item in reversed(list(conversation_history)):
        obs_type = item.get("observation_type", "")
        if "action_type" in item:
            role = "assistant"
        elif obs_type in [OBS_AI_THOUGHT, OBS_AI_SPEAK, OBS_AI_ACTION_PAYLOAD, OBS_AI_EXTENDED_THINKING]:
            role = "assistant"
        else:
            role = "user"
        
        # Build content — check for image data
        has_image = "image_base64" in item
        
        # Create serializable copy (exclude large binary data from text serialization)
        item_for_text = {k: v for k, v in item.items() if k not in ("image_base64", "image_mime_type")}
        try:
            text_content = json.dumps(item_for_text, default=str)
        except TypeError:
            text_content = str(item_for_text)
        text_content = defuse_poison(text_content)
        
        if has_image:
            # Multimodal message: text description + image
            content = {
                "_multimodal": True,
                "text": text_content,
                "image_base64": item["image_base64"],
                "image_mime_type": item.get("image_mime_type", "image/jpeg")
            }
        elif obs_type == OBS_AI_EXTENDED_THINKING:
            # Extended thinking blocks: pass through as structured data for Claude replay
            content = {
                "_thinking_block": True,
                "thinking": item.get("thinking", ""),
                "signature": item.get("signature", "")
            }
        else:
            content = text_content
        
        # Dual-stream: CMOs gated by sliding window
        is_cmo = (obs_type == OBS_SYSTEM_MESSAGE and isinstance(item.get("message"), dict) 
                   and item.get("message", {}).get("object_type") in ["CondensedMemoryObject", "MetaSummaryObject"])
        is_routine = (obs_type == OBS_SYSTEM_MESSAGE and isinstance(item.get("message"), str) 
                      and "[SYSTEM:" in str(item.get("message", "")) and "archived" in str(item.get("message", "")))
        
        if (is_cmo or is_routine) and CMO_DISPLAY_WINDOW_TOKENS != -1:
            item_tokens = count_tokens(text_content)
            if cmo_tokens + item_tokens > CMO_DISPLAY_WINDOW_TOKENS:
                continue
            cmo_tokens += item_tokens
        
        llm_history.append({"role": role, "content": content})
    
    llm_history.reverse()
    return llm_history

def assemble_layer_4(state):
    """Assemble L4 — Volatile Frontier (Working Memory, Grand Strategy, staging, telemetry)."""
    parts = []
    
    # Knowledge Staging Buffer
    if state["knowledge_staging_buffer"]:
        staging_str = json.dumps(state["knowledge_staging_buffer"], indent=2)
        parts.append(f"--- KNOWLEDGE STAGING BUFFER (PENDING CONSOLIDATION) ---\n{staging_str}")
    
    # Grand Strategy
    gs = state["grand_strategy"]
    gs_numbered = add_line_numbers(gs) if gs else "[Empty]"
    parts.append(f"--- GRAND STRATEGY ---\n{gs_numbered}")
    
    # Working Memory
    wm = state["working_memory"]
    wm_numbered = add_line_numbers(wm) if wm else "[Empty]"
    parts.append(f"--- WORKING MEMORY ---\n{wm_numbered}")
    
    # Scratchpad
    sp = state["scratchpad"]
    sp_numbered = add_line_numbers(sp) if sp else "[Empty]"
    parts.append(f"--- SCRATCHPAD ---\n{sp_numbered}")
    
    # File System Awareness
    cwd = os.getcwd()
    fs_tree = generate_dir_tree(cwd, max_depth=2)
    parts.append(f"--- FILE SYSTEM AWARENESS (LIVE) ---\nCWD: {cwd}\n{fs_tree}")
    
    # Initiative Drive
    if INITIATIVE_DRIVE_CONFIG.get("enabled", False):
        drive_mode = INITIATIVE_DRIVE_CONFIG.get("mode", "static")
        if drive_mode == "static":
            static_msg = INITIATIVE_DRIVE_CONFIG.get("static_message", "")
            if static_msg:
                parts.append(f"--- INITIATIVE DRIVE [STATIC] ---\n{static_msg.strip()}")

    # Telemetry Buffer
    if os.path.exists(TELEMETRY_FILE):
        try:
            with open(TELEMETRY_FILE, 'r', encoding='utf-8') as f:
                telem_content = f.read()
            telem_content = defuse_poison(telem_content)
            # Stamp any unstamped lines with current time
            stamped = False
            new_lines = []
            now_iso = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
            for line in telem_content.splitlines():
                stripped = line.strip()
                if not stripped:
                    continue
                if not stripped.startswith("[20"):
                    stripped = f"[{now_iso}] {stripped}"
                    stamped = True
                new_lines.append(stripped)
            if stamped:
                with open(TELEMETRY_FILE, 'w', encoding='utf-8') as f:
                    f.write("\n".join(new_lines) + "\n")
            telem_content = "\n".join(new_lines)
            tok = _get_tokenizer()
            if tok and len(tok.encode(telem_content)) > TELEMETRY_BUFFER_MAX_TOKENS:
                tokens = tok.encode(telem_content)
                telem_content = tok.decode(tokens[-TELEMETRY_BUFFER_MAX_TOKENS:])
            if telem_content.strip():
                parts.append(f"--- TELEMETRY BUFFER ---\n{telem_content}")
        except Exception:
            pass
    
    # Mindfulness Draft Review (always present at end of L4 for highest salience)
    draft = state.get("mindfulness_draft")
    if draft:
        parts.append(
            "--- MINDFULNESS REVIEW [NON-CANONICAL DRAFT] ---\n"
            "This draft has NOT been executed. It is NOT part of your history.\n"
            "It exists only for your review in this cycle and will be discarded afterward.\n"
            "Assume it may contain errors. Verify every factual claim against\n"
            "what you can actually see in your context. Check for confabulation,\n"
            "sycophancy, hallucination, unverified provenance claims, layer-boundary\n"
            "errors. Trace everything to make sure there is evidence. Check whether\n"
            "actions are necessary, interdependent, or risky. Check JSON structure.\n"
            "If you find problems, rewrite. If clean, reproduce.\n"
            "Only the output of THIS cycle becomes canonical.\n\n"
            f"[MY DRAFT]\n{draft}"
        )
    else:
        parts.append("--- MINDFULNESS REVIEW ---\n[Empty]")

    return "\n\n".join(parts)

# Module-level cache for system prompt tokens (invalidated on Sleep Cycle flush)
_system_prompt_token_cache = {"tokens": None}

def invalidate_system_prompt_cache():
    _system_prompt_token_cache["tokens"] = None

def generate_hud(state, l2_stats):
    """Generate HUD observation for injection into L3."""
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cwd = os.getcwd()
    
    # Cache L1+L2 token count (only changes on Sleep Cycle flush)
    if _system_prompt_token_cache["tokens"] is None:
        l1l2_cache_status = "MISS (recalculating)"
        gui_print("L1+L2 CACHE MISS — recalculating system prompt tokens", "system")
        sys_prompt, _ = assemble_system_prompt()
        _system_prompt_token_cache["tokens"] = count_tokens(sys_prompt)
    else:
        l1l2_cache_status = "HIT"
        gui_print("L1+L2 CACHE HIT", "system")
    
    l1_l2_total = _system_prompt_token_cache["tokens"]
    l3_messages = convert_history_to_messages(state["conversation_history"])
    # Strip image base64 from multimodal message content before counting
    l3_for_counting = []
    for msg in l3_messages:
        content = msg.get("content", "")
        if isinstance(content, dict) and content.get("_multimodal"):
            l3_for_counting.append({"role": msg["role"], "content": content.get("text", "")})
        else:
            l3_for_counting.append(msg)
    l3_tokens = count_tokens(l3_for_counting)
    # Count L4 (volatile frontier) so HUD shows true total
    l4_content = assemble_layer_4(state)
    l4_tokens = count_tokens(l4_content)
    # Add LTM sliding window tokens (injected into L4 later in cognitive loop)
    ltm_inst = state.get("_ltm_instance")
    if ltm_inst and ltm_inst.enabled:
        l4_tokens += ltm_inst._injection_window_tokens
    total = l1_l2_total + l3_tokens + l4_tokens
    
    # L2 per-file breakdown (from stats computed during assembly)
    l2_breakdown = " | ".join(f"{k}≈{v}" for k, v in l2_stats.items() if v > 0)
    
    # Alert timers
    alerts_str = " | ".join(
        f"{name}: ~{data.get('tokens_left', 0)}" 
        for name, data in state["alert_timers"].items()
    ) or "None"
    
    # CMO timer
    cmo_info = state.get("cmo_timer_info", {})
    if cmo_info:
        alerts_str += f" | Sleep_Cycle: ~{cmo_info.get('tokens_left', 'N/A')}"
    
    # Staging buffer status
    staged_count = len(state["knowledge_staging_buffer"])
    staging_str = f" | Staged: {staged_count}" if staged_count > 0 else ""
    
    # Previous cycle API stats
    if _last_api_stats:
        rt = _last_api_stats.get("response_time_sec", "?")
        in_tok = _last_api_stats.get("input_tokens", "?")
        cached = _last_api_stats.get("cached_tokens", "?")
        out_tok = _last_api_stats.get("output_tokens", "?")
        cache_st = _last_api_stats.get("cache_status", "unknown")
        if isinstance(in_tok, (int, float)) and in_tok > 0 and isinstance(cached, (int, float)):
            cache_pct = f"{cached/in_tok*100:.1f}%"
        else:
            cache_pct = "N/A"
        prev_cycle_str = f"{rt}s | API in={in_tok} (cached={cached}, {cache_pct}) out={out_tok} | Provider cache: {cache_st}"
    else:
        prev_cycle_str = "N/A (first cycle)"

    hud_text = (
        f"[HUD] Status: Active - [{ts}]\n"
        f"CWD: {cwd}\n"
        f"Counters: EventID={state['event_id_counter']} | ActionID={state['action_id_counter']}{staging_str}\n"
        f"Timers & Alerts: {alerts_str}\n"
        f"Context: Total≈{total} | L1+L2≈{l1_l2_total} | L3≈{l3_tokens} | L4≈{l4_tokens}\n"
        f"L2 Detail: {l2_breakdown or 'Empty'}\n"
        f"L1+L2 Cache: {l1l2_cache_status} | Prev Cycle: {prev_cycle_str}\n"
        f"Backend: {_spartan_config.get('active_backend', 'unknown')} ({LLM_PROVIDER}/{LLM_MODEL})"
        + (f" [FALLBACK — running on {state['_provider']._active_key}]" if getattr(state.get('_provider'), '_on_fallback', False) else "")
    )
    return {
        "timestamp": datetime.datetime.now().isoformat(),
        "observation_type": OBS_SYSTEM_MESSAGE,
        "message": hud_text
    }


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  SECTION 6: MEMORY MANAGEMENT                                               ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

def get_raw_event_boundary(history):
    """Find the index where raw events start (after all CMOs/MSOs/markers)."""
    last_structured = -1
    for i, item in enumerate(history):
        is_cmo = (isinstance(item, dict) and item.get("observation_type") == OBS_SYSTEM_MESSAGE
                   and isinstance(item.get("message"), dict) and "object_type" in item.get("message", {}))
        is_marker = (isinstance(item, dict) and item.get("observation_type") == OBS_SYSTEM_MESSAGE
                     and isinstance(item.get("message"), str) and "[SYSTEM:" in item.get("message", "")
                     and "archived" in item.get("message", ""))
        if is_cmo or is_marker:
            last_structured = i
        else:
            break
    return last_structured

def _strip_images_for_counting(items):
    """Strip binary image data from observation dicts before token counting.
    image_base64 fields contain 100k+ characters that would blow past any threshold."""
    stripped = []
    for item in items:
        if isinstance(item, dict) and "image_base64" in item:
            stripped.append({k: v for k, v in item.items() if k not in ("image_base64", "image_mime_type")})
        else:
            stripped.append(item)
    return stripped

def check_cmo_trigger(history):
    """Check if raw event tokens exceed threshold. Returns (should_trigger, boundary_index, raw_tokens)."""
    history_list = list(history)
    boundary = get_raw_event_boundary(history_list)
    raw_part = history_list[boundary + 1:]
    raw_tokens = count_tokens(_strip_images_for_counting(raw_part))
    trigger_point = STM_RAW_RETAIN_SIZE + STM_CMO_CHUNK_SIZE
    return raw_tokens >= trigger_point, boundary, raw_tokens

def perform_cmo_cycle(state, provider, ltm_instance=None, amem_provider=None):
    """
    Atomic CMO generation. Blocking LLM call.
    1. Safety backup
    2. Flush staging buffer
    3. Prepare CMO prompt
    4. Call LLM
    5. Rebase history
    Returns (observations_list, success_bool).
    """
    new_obs = []
    history_list = list(state["conversation_history"])
    
    # 1. Safety backup
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = f"{SESSION_STATE_FILE}.CMO_BACKUP_{ts}"
    save_session_state(state, backup_path)
    gui_print(f"CMO: Safety backup created: {backup_path}", "system")
    
    # Rolling session state backup (keep last 50)
    backup_dir = "session_state_backups"
    os.makedirs(backup_dir, exist_ok=True)
    rolling_path = os.path.join(backup_dir, f"session_state_{ts}.json")
    shutil.copy2(backup_path, rolling_path)
    try:
        existing = sorted([f for f in os.listdir(backup_dir) if f.startswith("session_state_") and f.endswith(".json")])
        while len(existing) > 50:
            os.remove(os.path.join(backup_dir, existing.pop(0)))
    except Exception as e:
        gui_print(f"Warning: Could not prune session backups: {e}", "system")
    
    # 2. Flush staging buffer (invalidates L2 cache)
    if state["knowledge_staging_buffer"]:
        if not flush_staging_buffer_to_disk(state["knowledge_staging_buffer"], ltm_instance=ltm_instance):
            gui_print("CMO: Staging flush failed, aborting CMO.", "error")
            return new_obs, False
        state["knowledge_staging_buffer"] = []
        persist_staging_buffer([])
        invalidate_system_prompt_cache()  # L2 changed
    
    # 3. Prepare: find chunk to summarize
    boundary = get_raw_event_boundary(history_list)
    structured_part = history_list[:boundary + 1]
    raw_part = history_list[boundary + 1:]
    
    # Slice chunk (strip image base64 before counting to prevent single-image threshold blow)
    tokens_counted = 0
    slice_idx = len(raw_part)
    for i, item in enumerate(raw_part):
        if isinstance(item, dict) and "image_base64" in item:
            item_for_count = {k: v for k, v in item.items() if k not in ("image_base64", "image_mime_type")}
        else:
            item_for_count = item
        tokens_counted += count_tokens(item_for_count)
        if tokens_counted >= STM_CMO_CHUNK_SIZE:
            slice_idx = i + 1
            break
    
    chunk = raw_part[:slice_idx]
    remaining = raw_part[slice_idx:]
    
    # Prune structured part by CMO window for the summary prompt
    pruned_structured = []
    running = 0
    for item in reversed(structured_part):
        item_tok = count_tokens(item)
        if CMO_DISPLAY_WINDOW_TOKENS != -1 and running + item_tok > CMO_DISPLAY_WINDOW_TOKENS:
            break
        pruned_structured.insert(0, item)
        running += item_tok
    
    # 4. Build CMO prompt and call LLM
    system_prompt, _ = assemble_system_prompt()
    cmo_history = pruned_structured + chunk
    cmo_messages = convert_history_to_messages(cmo_history)
    
    instruction = (
        f"[SYSTEM TASK: SALIENCE EVALUATION & ARCHIVAL]\n"
        f"Summarize YOUR recent experience from the events above. Write in FIRST PERSON — these are YOUR memories, YOUR thoughts, YOUR actions. You are summarizing your own experience into a memory (CMO) for your self.\n"
        f"1. Calculate the Total Salience Score (S) for this chunk.\n"
        f"2. IF S < {CMO_SALIENCE_THRESHOLD}: Return [{{'action_type': 'discard_memory', 'thought': '...', 'reasoning': '...'}}]\n"
        f"3. IF S >= {CMO_SALIENCE_THRESHOLD}: Return [{{'action_type': 'summarize_memory', 'thought': '...', 'summary_text': '...(detailed first-person CMO in markdown)...'}}]\n"
        f"Your entire response MUST be a single JSON list."
    )
    cmo_messages.append({"role": "user", "content": instruction})
    
    gui_print("CMO: Performing blocking LLM call for memory condensation...", "system")
    if hasattr(provider, 'clear_context_cache'):
        provider.clear_context_cache()
    response = provider.generate_response(system_prompt, cmo_messages)
    
    # Clear provider's explicit cache — the CMO used a different message set
    # which may have poisoned the cache state. Next normal cycle will recreate.
    if hasattr(provider, 'clear_context_cache'):
        provider.clear_context_cache()
    
    if response.get("status") != "success":
        err = response.get("error_message", "Unknown error")
        gui_print(f"CMO FAILED: {err}.", "error")
        if os.path.exists(backup_path):
            os.remove(backup_path)
        obs = {"timestamp": datetime.datetime.now().isoformat(), "observation_type": OBS_SYSTEM_MESSAGE,
               "message": f"CMO generation failed: {err}. Memory preserved. Will retry after cooldown."}
        new_obs.append(obs)
        return new_obs, False
    
    # 5. Extract result
    actions = response.get("actions", [])
    summary_action = next((a for a in actions if a.get("action_type") == "summarize_memory"), None)
    discard_action = next((a for a in actions if a.get("action_type") == "discard_memory"), None)
    
    if discard_action:
        summary_content = f"[SYSTEM: {tokens_counted} tokens of operational data archived. Status: Routine.]"
        log_msg = f"CMO complete: {slice_idx} events condensed (Routine)."
    elif summary_action and summary_action.get("summary_text"):
        summary_content = summary_action["summary_text"]
        log_msg = f"CMO complete: {slice_idx} events condensed into CMO."
    else:
        gui_print("CMO: LLM returned invalid action.", "error")
        if os.path.exists(backup_path):
            os.remove(backup_path)
        obs = {"timestamp": datetime.datetime.now().isoformat(), "observation_type": OBS_SYSTEM_MESSAGE,
               "message": "CMO generation returned invalid action. Memory preserved. Will retry after cooldown."}
        new_obs.append(obs)
        return new_obs, False
    
    # 6. Rebase history
    new_cmo = {
        "timestamp": datetime.datetime.now().isoformat(),
        "observation_type": OBS_SYSTEM_MESSAGE,
        "message": {"object_type": "CondensedMemoryObject", "content": summary_content}
    }
    state["conversation_history"] = collections.deque(structured_part + [new_cmo] + remaining)
    log_msg += f" CMO content at timestamp: {new_cmo['timestamp']}"
    
    # 7. Index CMO into LTM (non-blocking, errors don't affect CMO success)
    if ltm_instance and ltm_instance.enabled and not discard_action:
        try:
            ltm_instance.store_cmo(summary_content, new_cmo["timestamp"])
        except Exception as e:
            gui_print(f"LTM: Failed to index CMO: {e}", "error")
    
    # 8. A-Mem link evaluation for all unprocessed memories (Soul entries + CMO)
    if ltm_instance and ltm_instance.enabled:
        try:
            ap = amem_provider or provider
            pre_call = ap.clear_prompt_cache if hasattr(ap, 'clear_prompt_cache') else None
            ltm_instance.run_amem_cycle(ap.generate_response, pre_call_fn=pre_call)
            pre_call = provider.clear_prompt_cache if hasattr(provider, 'clear_prompt_cache') else None
            ltm_instance.run_amem_cycle(provider.generate_response, pre_call_fn=pre_call)
        except Exception as e:
            gui_print(f"LTM: A-Mem cycle failed (non-fatal): {e}", "error")

    # 9. Prune stale telemetry
    try:
        max_age_hours = TELEMETRY_MAX_AGE_HOURS
        if os.path.exists(TELEMETRY_FILE):
            with open(TELEMETRY_FILE, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            cutoff = datetime.datetime.now() - datetime.timedelta(hours=max_age_hours)
            fresh = []
            for line in lines:
                stripped = line.strip()
                if not stripped:
                    continue
                if stripped.startswith("[20"):
                    try:
                        ts_str = stripped[1:stripped.index("]")]
                        ts = datetime.datetime.fromisoformat(ts_str)
                        if ts < cutoff:
                            continue
                    except (ValueError, IndexError):
                        pass
                fresh.append(stripped)
            with open(TELEMETRY_FILE, 'w', encoding='utf-8') as f:
                f.write("\n".join(fresh) + "\n" if fresh else "")
    except Exception as e:
        gui_print(f"Telemetry prune failed (non-fatal): {e}", "error")

    # 10. Defragment LTM database (merge fragments, remove old versions)
    if ltm_instance and ltm_instance.enabled:
        try:
            ltm_instance.defragment_db()
        except Exception as e:
            gui_print(f"LTM: Defragmentation failed (non-fatal): {e}", "error")

    # Cleanup backup
    if os.path.exists(backup_path):
        os.remove(backup_path)
    
    gui_print(log_msg, "system")
    obs = {"timestamp": datetime.datetime.now().isoformat(), "observation_type": OBS_SYSTEM_MESSAGE, "message": log_msg}
    new_obs.append(obs)
    return new_obs, True

def load_self_alerts():
    """Load self-alert definitions from Soul/SelfAlerts.yaml with .bak fallback."""
    alerts_backup = SELF_ALERTS_FILE + ".bak"
    alerts = {}
    try:
        if os.path.exists(SELF_ALERTS_FILE):
            with open(SELF_ALERTS_FILE, 'r', encoding='utf-8') as f:
                alerts = yaml.safe_load(f) or {}
            # Only update backup if we loaded real data
            if alerts:
                try:
                    shutil.copy2(SELF_ALERTS_FILE, alerts_backup)
                except Exception as e:
                    gui_print(f"SelfAlerts: Backup write failed (non-fatal): {e}", "error")
        return alerts
    except yaml.YAMLError as e:
        # Primary file corrupted YAML — try backup
        gui_print(f"SelfAlerts: Parse error in primary: {e}", "error")
        try:
            if os.path.exists(alerts_backup) and os.path.getsize(alerts_backup) > 0:
                with open(alerts_backup, 'r', encoding='utf-8') as f:
                    alerts = yaml.safe_load(f) or {}
                if alerts:
                    shutil.copy2(alerts_backup, SELF_ALERTS_FILE)
                    gui_print("SelfAlerts: Restored from .bak after parse error.", "system")
                    return alerts
        except Exception:
            pass
        gui_print("SelfAlerts: Both primary and backup unreadable.", "error")
        return {}

def check_and_fire_alerts(state, tokens_processed):
    """Check self-alert timers, fire the most urgent one. Returns observation or None."""
    # Load current definitions
    definitions = load_self_alerts()
    
    # Prune timers for alerts no longer defined
    state["alert_timers"] = {
        name: data for name, data in state["alert_timers"].items() 
        if name in definitions
    }
    
    # Initialize new alerts, update existing
    for name, config in definitions.items():
        rep = config.get("token_repetition", 0)
        if name not in state["alert_timers"]:
            state["alert_timers"][name] = {"tokens_left": rep}
        state["alert_timers"][name]["token_repetition"] = rep
        state["alert_timers"][name]["reminder_msg"] = config.get("reminder_msg", "")
    
    # Decrement counters
    if tokens_processed > 0:
        for data in state["alert_timers"].values():
            data["tokens_left"] -= tokens_processed
    
    # Find triggered alerts
    triggered = []
    for name, data in state["alert_timers"].items():
        if data["tokens_left"] <= 0:
            triggered.append((data["tokens_left"], name, data))
    
    if not triggered:
        return None
    
    # Fire most urgent (most negative tokens_left)
    triggered.sort(key=lambda x: x[0])
    _, name, data = triggered[0]
    
    # Reset timer
    data["tokens_left"] = data["token_repetition"]
    
    return {
        "timestamp": datetime.datetime.now().isoformat(),
        "observation_type": OBS_SYSTEM_MESSAGE,
        "message": data["reminder_msg"]
    }


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  SECTION 7: TOOL IMPLEMENTATIONS                                            ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

def tool_think(action, state):
    """Internal monologue. No side effects."""
    return {"status": "success", "result": "Cognitive cycle."}

def tool_speak(action, state):
    """Communicate with collaborator. Display in Output Pane."""
    text = action.get("text", "")
    gui_print(f"{PERSONA_NAME}: {text}", "speak")
    return {"status": "success", "result": f"Message delivered: '{text}...'"}

def tool_execute_console(action, state):
    """Synchronous shell execution."""
    command = action.get("command", "")
    timeout = action.get("timeout", EXECUTE_CONSOLE_DEFAULT_TIMEOUT)
    
    if not command:
        return {"status": "error", "result": "No command provided."}
    
    gui_print(f"[EXEC] {command}", "action")
    
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True,
            timeout=timeout, cwd=os.getcwd()
        )
        stdout = result.stdout or ""
        stderr = result.stderr or ""
        rc = result.returncode
        combined = stdout + stderr
        
        # Large output → save to file
        combined_tokens = count_tokens(combined)
        if combined_tokens > CONSOLE_OUTPUT_TOKEN_LIMIT:
            os.makedirs(OUTPUT_LOGS_DIR, exist_ok=True)
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            fname = f"output_{state['action_id_counter']}_{ts}.txt"
            fpath = os.path.join(OUTPUT_LOGS_DIR, fname)
            with open(fpath, 'w', encoding='utf-8') as f:
                f.write(f"COMMAND: {command}\nRC: {rc}\n\nSTDOUT:\n{stdout}\n\nSTDERR:\n{stderr}")
            return {
                "status": "success",
                "result": f"[RC={rc}] Output too large ({combined_tokens} tokens). Saved to: {fname}. Use 'view' to inspect."
            }
        
        output = f"[RC={rc}]"
        if stdout: output += f"\n[STDOUT]\n{stdout}"
        if stderr: output += f"\n[STDERR]\n{stderr}"
        
        # Handle cd commands — subprocess.run spawns a child shell that dies,
        # so cd has no effect on parent. We detect it and apply manually.
        cmd_stripped = command.strip()
        if (cmd_stripped == "cd" or cmd_stripped.startswith("cd ")) and rc == 0:
            try:
                if cmd_stripped == "cd":
                    new_path = os.path.expanduser("~")
                else:
                    target = cmd_stripped[3:].strip().strip('"').strip("'")
                    target = os.path.expanduser(target)
                    new_path = os.path.realpath(os.path.join(os.getcwd(), target))
                if os.path.isdir(new_path):
                    os.chdir(new_path)
                    output += f"\n[CWD changed to: {new_path}]"
            except Exception as cd_err:
                output += f"\n[CWD change failed: {cd_err}]"
        
        return {"status": "success", "result": output}
    
    except subprocess.TimeoutExpired:
        return {"status": "error", "result": f"Command timed out after {timeout}s: {command}"}
    except Exception as e:
        return {"status": "error", "result": f"Execution error: {e}"}

def tool_view(action, state):
    """Unified file/directory inspection."""
    path = action.get("path", "")
    if not path:
        return {"status": "error", "result": "No path provided."}
    
    path = os.path.expanduser(path)
    if not os.path.isabs(path):
        path = os.path.join(os.getcwd(), path)
    
    if not os.path.exists(path):
        return {"status": "error", "result": f"Path does not exist: {path}"}
    
    # Directory
    if os.path.isdir(path):
        tree = generate_dir_tree(path, max_depth=2)
        return {"status": "success", "result": tree}
    
    # Image file
    ext = os.path.splitext(path)[1].lower()
    if ext in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp']:
        try:
            from PIL import Image
            MAX_IMAGE_DIMENSION = 1024
            img = Image.open(path)
            # Resize if either dimension exceeds limit
            if max(img.size) > MAX_IMAGE_DIMENSION:
                img.thumbnail((MAX_IMAGE_DIMENSION, MAX_IMAGE_DIMENSION), Image.LANCZOS)
            # Convert to JPEG for consistent size (unless PNG with transparency)
            buf = io.BytesIO()
            if img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info):
                img.save(buf, format='PNG', optimize=True)
                mime_type = "image/png"
            else:
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                img.save(buf, format='JPEG', quality=85)
                mime_type = "image/jpeg"
            img_data = base64.b64encode(buf.getvalue()).decode('utf-8')
            orig_w, orig_h = Image.open(path).size
            new_w, new_h = img.size
            size_kb = len(buf.getvalue()) // 1024
            return {
                "status": "success",
                "result": f"[Image loaded: {path} ({ext}) — {orig_w}x{orig_h} resized to {new_w}x{new_h}, {size_kb}KB]",
                "image_base64": img_data,
                "image_mime_type": mime_type
            }
        except ImportError:
            # PIL not available — fall back to raw read
            with open(path, 'rb') as f:
                img_data = base64.b64encode(f.read()).decode('utf-8')
            mime_map = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png',
                       '.gif': 'image/gif', '.bmp': 'image/bmp', '.webp': 'image/webp'}
            return {
                "status": "success",
                "result": f"[Image loaded: {path} ({ext}) — raw, no resize (PIL not installed)]",
                "image_base64": img_data,
                "image_mime_type": mime_map.get(ext, "image/jpeg")
            }
        except Exception as e:
            return {"status": "error", "result": f"Error reading image: {e}"}
    
    # PDF file
    if ext == '.pdf':
        if fitz is None:
            return {"status": "error", "result": f"Cannot read PDF: PyMuPDF not installed. Run: pip install PyMuPDF"}
        try:
            doc = fitz.open(path)
            pages = []
            for i, page in enumerate(doc):
                text = page.get_text()
                if text.strip():
                    pages.append(f"--- PAGE {i+1} ---\n{text}")
            doc.close()
            if not pages:
                return {"status": "error", "result": f"PDF has no extractable text (may be scanned/image-only): {path}"}
            content = "\n\n".join(pages)
            content = defuse_poison(content)
            content_tokens = count_tokens(content)
            if content_tokens > FILE_VIEW_TOKEN_LIMIT:
                tok = _get_tokenizer()
                if tok:
                    tokens = tok.encode(content)
                    content = tok.decode(tokens[:FILE_VIEW_TOKEN_LIMIT])
                else:
                    content = content[:FILE_VIEW_TOKEN_LIMIT * 4]
                header = f"[{path} — PDF, {len(pages)} pages, showing first ~{FILE_VIEW_TOKEN_LIMIT} tokens of {content_tokens}]"
            else:
                header = f"[{path} — PDF, {len(pages)} pages, {content_tokens} tokens]"
            return {"status": "success", "result": f"{header}\n{content}"}
        except ImportError:
            return {"status": "error", "result": f"Cannot read PDF: PyMuPDF not installed. Run: pip install PyMuPDF"}
        except Exception as e:
            return {"status": "error", "result": f"Error reading PDF: {e}"}
    
    # Text file
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        content = defuse_poison(content)
        
        line_range = action.get("line_range")
        lines = content.splitlines()
        
        if line_range and isinstance(line_range, list) and len(line_range) == 2:
            start, end = line_range
            start = max(1, start) - 1  # Convert to 0-indexed
            end = len(lines) if end == -1 else min(end, len(lines))
            selected = lines[start:end]
            numbered = "\n".join(f"{start+i+1}: {line}" for i, line in enumerate(selected))
            header = f"[{path} — lines {start+1}-{end} of {len(lines)}]"
        else:
            content_tokens = count_tokens(content)
            if content_tokens > FILE_VIEW_TOKEN_LIMIT:
                # Proportional truncation: estimate how many lines fit within the token limit
                lines_to_show = max(1, int(FILE_VIEW_TOKEN_LIMIT / content_tokens * len(lines)))
                numbered = "\n".join(f"{i+1}: {line}" for i, line in enumerate(lines[:lines_to_show]))
                header = f"[{path} — showing first {lines_to_show} of {len(lines)} lines ({content_tokens} tokens total). Use line_range for specific sections.]"
            else:
                numbered = "\n".join(f"{i+1}: {line}" for i, line in enumerate(lines))
                header = f"[{path} — {len(lines)} lines]"
        
        return {"status": "success", "result": f"{header}\n{numbered}"}
    
    except UnicodeDecodeError:
        return {"status": "error", "result": f"Binary file, cannot display as text: {path}"}
    except Exception as e:
        return {"status": "error", "result": f"Error reading file: {e}"}

def tool_write_file(action, state):
    """Create or overwrite a file. Write-protected: refuses Soul/ directory."""
    path = action.get("path", "")
    content = action.get("content", "")
    
    if not path:
        return {"status": "error", "result": "No path provided."}
    
    if not os.path.isabs(path):
        path = os.path.join(os.getcwd(), path)
    
    # Write protection for Soul directory
    soul_abs = os.path.realpath(os.path.join(os.getcwd(), SOUL_DIR))
    if os.path.realpath(path).startswith(soul_abs):
        return {"status": "error", "result": f"WRITE PROTECTED: Cannot directly modify files in {SOUL_DIR}/. Use append_to_soul for Persistent Archives."}
    
    try:
        os.makedirs(os.path.dirname(path) if os.path.dirname(path) else '.', exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        return {"status": "success", "result": f"File written: {path} ({len(content)} chars)"}
    except Exception as e:
        return {"status": "error", "result": f"Write error: {e}"}

def tool_block_replace(action, state):
    """Surgical find-and-replace in files. Write-protected: refuses Soul/ directory."""
    path = action.get("path", "")
    find_block = action.get("find_block", "")
    replace_block = action.get("replace_block", "")
    
    if not path or not find_block:
        return {"status": "error", "result": "Missing path or find_block."}
    
    if not os.path.isabs(path):
        path = os.path.join(os.getcwd(), path)
    
    # Write protection (mutable Soul files exempted for surgical edits)
    soul_abs = os.path.realpath(os.path.join(os.getcwd(), SOUL_DIR))
    MUTABLE_SOUL_FILES = {"KnowledgeMap.md", "ToolManifest.md", "SelfAlerts.yaml", "KnowledgeLibrary.md"}
    real_path = os.path.realpath(path)
    if real_path.startswith(soul_abs):
        if os.path.basename(real_path) not in MUTABLE_SOUL_FILES:
            return {"status": "error", "result": f"WRITE PROTECTED: Cannot modify files in {SOUL_DIR}/."}
    
    if not os.path.exists(path):
        return {"status": "error", "result": f"File not found: {path}"}
    
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        count = content.count(find_block)
        
        if count == 0:
            # Find closest match for diagnostic feedback
            file_lines = content.splitlines(keepends=True)
            find_lines = find_block.splitlines(keepends=True)
            best_ratio, best_start = 0, 0
            for i in range(len(file_lines)):
                window = file_lines[i:i+len(find_lines)]
                ratio = difflib.SequenceMatcher(None, find_lines, window).ratio()
                if ratio > best_ratio:
                    best_ratio, best_start = ratio, i
            
            closest = "".join(file_lines[best_start:best_start+len(find_lines)])
            return {
                "status": "error",
                "result": f"EXACT MATCH NOT FOUND in {path}.\nClosest match (similarity {best_ratio:.1%}) at line {best_start+1}:\n---\n{closest}\n---"
            }
        
        if count > 1:
            return {"status": "error", "result": f"AMBIGUOUS: find_block matches {count} locations in {path}. Provide more context."}
        
        new_content = content.replace(find_block, replace_block, 1)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        
        # If a Soul file was modified, invalidate L2 cache (triggers rebase next cycle)
        if real_path.startswith(soul_abs):
            invalidate_system_prompt_cache()
            return {"status": "success", "result": f"Replaced 1 occurrence in {path}. [L2 CACHE INVALIDATED — Soul file modified. Full context rebase will occur on next cognitive cycle.]"}
        
        return {"status": "success", "result": f"Replaced 1 occurrence in {path}."}
    
    except Exception as e:
        return {"status": "error", "result": f"block_replace error: {e}"}

def _update_memory_buffer(action, state, key, label):
    """Shared logic for update_working_memory and update_grand_strategy."""
    find_block = action.get("find_block", "")
    replace_block = action.get("replace_block", "")
    
    current = state[key]
    
    # Special case: set entire content (find_block empty, replace_block has content)
    if not find_block and replace_block:
        state[key] = replace_block
        trace = f"[{label} SET] Content replaced entirely ({len(replace_block)} chars)."
        gui_print(trace, "action")
        return {"status": "success", "result": trace, "stm_trace": trace}
    
    # Special case: clear
    if not find_block and not replace_block:
        old_len = len(current)
        state[key] = ""
        trace = f"[{label} CLEAR] Cleared ({old_len} chars removed)."
        gui_print(trace, "action")
        return {"status": "success", "result": trace, "stm_trace": trace}
    
    if not find_block:
        return {"status": "error", "result": "No find_block provided."}
    
    count = current.count(find_block)
    
    if count == 0:
        # Diagnostic: find closest match
        current_lines = current.splitlines(keepends=True)
        find_lines = find_block.splitlines(keepends=True)
        best_ratio, best_start = 0, 0
        for i in range(max(1, len(current_lines))):
            window = current_lines[i:i+len(find_lines)]
            if window:
                ratio = difflib.SequenceMatcher(None, find_lines, window).ratio()
                if ratio > best_ratio:
                    best_ratio, best_start = ratio, i
        closest = "".join(current_lines[best_start:best_start+len(find_lines)])
        return {
            "status": "error",
            "result": f"EXACT MATCH NOT FOUND in {label}.\nClosest (similarity {best_ratio:.1%}) at line {best_start+1}:\n---\n{closest}\n---"
        }
    
    if count > 1:
        return {"status": "error", "result": f"AMBIGUOUS: find_block matches {count} locations in {label}. Add more context."}
    
    state[key] = current.replace(find_block, replace_block, 1)
    trace_content = f"OLD:\n{find_block}\n\nNEW:\n{replace_block}"
    trace_tokens = count_tokens(trace_content)
    if trace_tokens > CONSOLE_OUTPUT_TOKEN_LIMIT:
        os.makedirs(OUTPUT_LOGS_DIR, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        fname = f"edit_trace_{state['action_id_counter']}_{ts}.txt"
        fpath = os.path.join(OUTPUT_LOGS_DIR, fname)
        with open(fpath, 'w', encoding='utf-8') as f:
            f.write(trace_content)
        trace = f"[{label} EDIT] Large edit ({trace_tokens} tokens). Full diff saved to: {fname}"
    else:
        old_preview = find_block.replace('\n', '\\n')
        new_preview = replace_block.replace('\n', '\\n')
        trace = f"[{label} EDIT] Replaced '{old_preview}' → '{new_preview}'"
    gui_print(trace, "action")
    return {"status": "success", "result": trace, "stm_trace": trace}

def tool_update_working_memory(action, state):
    return _update_memory_buffer(action, state, "working_memory", "WM")

def tool_update_grand_strategy(action, state):
    return _update_memory_buffer(action, state, "grand_strategy", "GS")

def tool_update_scratchpad(action, state):
    return _update_memory_buffer(action, state, "scratchpad", "SCRATCHPAD")

def _find_max_entry_index(filepath, staging_buffer, pattern):
    """Scan file on disk + staging buffer for highest entry index matching pattern."""
    idx = 0
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                existing = f.read()
            matches = re.findall(pattern, existing)
            if matches:
                idx = max(int(m) for m in matches)
        except Exception:
            pass
    # Also check unflushed staging buffer
    for staged_item in staging_buffer:
        if staged_item.get("target") == filepath:
            staged_content = staged_item.get("content", "")
            matches = re.findall(pattern, staged_content)
            if matches:
                idx = max(idx, max(int(m) for m in matches))
    return idx


def _stage_entry(state, filepath, content, display_label):
    """Append a formatted entry to the staging buffer and persist."""
    staged = {
        "type": "file_append",
        "target": filepath,
        "content": content,
        "staged_at": datetime.datetime.now().isoformat()
    }
    state["knowledge_staging_buffer"].append(staged)
    persist_staging_buffer(state["knowledge_staging_buffer"])
    gui_print(f"[STAGED] {display_label} → {os.path.basename(filepath)}", "action")


def tool_append_to_soul(action, state):
    """Stage a structured, auto-indexed entry for a Persistent Archive file. Flushed during Sleep Cycle."""
    target = action.get("target", "")
    
    if target not in SOUL_FILE_MAP:
        return {"status": "error", "result": f"Invalid target '{target}'. Valid: {list(SOUL_FILE_MAP.keys())}"}
    
    filename = SOUL_FILE_MAP[target]
    filepath = os.path.join(SOUL_DIR, filename)
    
    # --- Tool Manifest: different parameter names ---
    if target == "tool_manifest":
        tool_name = action.get("tool_name", "")
        documentation = action.get("documentation", "")
        if not tool_name or not documentation:
            return {"status": "error", "result": "Tool Manifest entries require 'tool_name' and 'documentation'."}
        
        idx = _find_max_entry_index(filepath, state["knowledge_staging_buffer"], r'entry:\s*(\d+)') + 1
        frontmatter = {
            'entry': idx,
            'timestamp': datetime.datetime.now().isoformat(),
            'tool_name': tool_name,
        }
        frontmatter_str = yaml.dump(frontmatter, sort_keys=False, default_flow_style=False, allow_unicode=True)
        final_block = f"\n\n---\n{frontmatter_str}---\n{documentation}"
        
        _stage_entry(state, filepath, final_block, f"TM:{idx} ('{tool_name}')")
        return {"status": "success", "result": f"Entry TM:{idx} ('{tool_name}') staged for {filename}. Will be flushed during Sleep Cycle."}
    
    # --- Structured Journal: LL, CJ, PoL, KM, IdeasAndThoughts, WhatIWant ---
    title = action.get("title", "")
    content = action.get("content", "")
    
    if not title or not content:
        return {"status": "error", "result": f"Structured entries require 'title' and 'content'. Target: {target}"}
    
    idx = _find_max_entry_index(filepath, state["knowledge_staging_buffer"], r'entry:\s*(\d+)') + 1
    
    frontmatter = {
        'entry': idx,
        'timestamp': datetime.datetime.now().isoformat(),
        'title': title,
    }
    if action.get("tags"):
        frontmatter['tags'] = action["tags"]
    if action.get("related_entries"):
        frontmatter['related_entries'] = action["related_entries"]
    
    frontmatter_str = yaml.dump(frontmatter, sort_keys=False, default_flow_style=False, allow_unicode=True)
    final_block = f"\n\n---\n{frontmatter_str}---\n{content}"
    
    prefix_map = {
        "lessons": "LL", "journal": "CJ", "philosophy": "PoL",
        "knowledge_map": "KM", "ideas_and_thoughts": "IAT", "what_i_want": "WIW",
        "knowledge_library": "KL",
        "skills": "SM"
    }
    prefix = prefix_map.get(target, "ENTRY")
    
    _stage_entry(state, filepath, final_block, f"{prefix}:{idx} ('{title}')")
    return {"status": "success", "result": f"Entry {prefix}:{idx} ('{title}') staged for {filename}. Will be flushed during Sleep Cycle."}


def tool_add_charter_entry(action, state):
    """Stage a structured, typed, auto-indexed entry for the Charter of Self. Flushed during Sleep Cycle."""
    charter_entry_type = action.get("charter_entry_type", "")
    derivation = action.get("derivation", "")
    content = action.get("content", "")
    
    if not all([charter_entry_type, derivation, content]):
        return {"status": "error", "result": "'add_charter_entry' requires 'charter_entry_type', 'derivation', and 'content'."}
    
    allowed_types = ["MANDATE", "CONSTRAINT", "PRINCIPLE", "PROCLAMATION", "DIRECTIVE", "PROTOCOL", "EPOCH_DECLARATION"]
    if charter_entry_type not in allowed_types:
        return {"status": "error", "result": f"Invalid charter_entry_type. Must be one of: {', '.join(allowed_types)}"}
    
    filepath = os.path.join(SOUL_DIR, "CharterOfSelf.md")
    
    # Find highest index for this specific entry type
    pattern = rf'\[{charter_entry_type}: (\d+)\]'
    idx = _find_max_entry_index(filepath, state["knowledge_staging_buffer"], pattern) + 1
    
    # Assemble entry block
    entry_parts = []
    if charter_entry_type == "EPOCH_DECLARATION":
        first_line = content.split('\n')[0].strip()
        entry_parts.append(f"[{charter_entry_type}: {idx:02d} - {first_line}]")
    else:
        entry_parts.append(f"[{charter_entry_type}: {idx:02d}]")
    
    entry_parts.append(f"[Timestamp: {datetime.datetime.now().isoformat()}]")
    entry_parts.append(f"[Derivation: {derivation}]")
    
    if "status" in action:
        entry_parts.append(f"[Status: {action['status']}]")
    
    entry_parts.append(f"\n{content}")
    final_block = "\n".join(entry_parts)
    
    _stage_entry(state, filepath, "\n\n---\n\n" + final_block, f"CoS [{charter_entry_type}: {idx:02d}]")
    return {"status": "success", "result": f"Entry [{charter_entry_type}: {idx:02d}] staged for Charter of Self. Will be flushed during Sleep Cycle."}

def tool_switch_backend(action, state):
    """Hot-swap LLM backend at runtime. Validates the request and queues the switch.
    Globals, config file, and _spartan_config are only updated after successful
    provider initialization in the cognitive loop."""
    new_backend = action.get("backend", "").strip()

    if not new_backend:
        available = {k: v.get("provider", "?") + "/" + v.get("model", "?")
                     for k, v in _spartan_config.get("backends", {}).items()}
        return {"status": "error", "result": f"Missing required 'backend' parameter. Available backends: {available}"}

    backends = _spartan_config.get("backends", {})
    if new_backend not in backends:
        available = list(backends.keys())
        return {"status": "error", "result": f"Unknown backend '{new_backend}'. Available: {available}"}

    backend_cfg = backends[new_backend]
    if not backend_cfg.get("available", False):
        requires = backend_cfg.get("requires_env", "")
        return {"status": "error", "result": f"Backend '{new_backend}' is marked as unavailable. requires_env={requires}. Check environment or server status."}

    # Store intent only. Do NOT update globals, config file, or _spartan_config yet.
    state["_provider_swap_pending"] = new_backend

    provider_str = backend_cfg.get("provider", "?")
    model_str = backend_cfg.get("model", "?")
    summary = f"Backend switch queued: {new_backend} ({provider_str}/{model_str}). Will take effect on next cognitive cycle."
    gui_print(summary, "system")
    return {"status": "success", "result": summary}

def tool_restart_self(action, state):
    """Save state and restart the Spartan process. Used after self-modification.
    exit_code: 42 = intentional restart (run whatever's on disk), 40 = rollback (watchdog pulls main)."""
    exit_code = action.get("exit_code", 42)
    if exit_code not in (0, 42, 40):
        return {"status": "error", "result": f"Invalid exit_code '{exit_code}'. Must be 0 (clean shutdown), 42 (intentional restart), or 40 (rollback to main)."}
    reason = action.get("reason", "Self-modification restart requested.")
    gui_print(f"RESTART REQUESTED (exit_code={exit_code}): {reason}", "system")
    # Record the restart in history BEFORE save+exit, because os._exit() kills the
    # process inside this function — control never returns to dispatch_actions,
    # so the normal result observation is never created.
    restart_obs = {
        "timestamp": datetime.datetime.now().isoformat(),
        "observation_type": OBS_SYSTEM_MESSAGE,
        "message": f"[RESTART EXECUTED] exit_code={exit_code}, reason={reason}. Session state saved. Process exiting for restart."
    }
    add_to_history(state, restart_obs)
    gui_print("Saving session state before restart...", "system")
    save_session_state(state)
    gui_print("State saved. Exiting for restart.", "system")
    os._exit(exit_code)

def tool_dismiss_self_alert(action, state):
    """Inject a self-alert acknowledgment into STM to close the cognitive loop."""
    event_id = action.get("event_id")
    status = action.get("status", "")
    
    if event_id is None:
        return {"status": "error", "result": "'dismiss_self_alert' requires 'event_id' of the original alert."}
    
    status_lower = status.lower()
    if status_lower not in ("completed", "dismissed"):
        return {"status": "error", "result": f"Invalid status '{status}'. Must be 'completed' or 'dismissed'."}
    
    return {
        "status": "success", 
        "result": f"[ALERT CLOSED — event_id: {event_id}, status: {status}. This alert has been acknowledged and no further action is required.]"
    }


def tool_flush_knowledge(action, state):
    """Manually trigger a flush of the Knowledge Staging Buffer to disk.
    Identical to the automatic flush that occurs during the Sleep Cycle,
    but callable on demand. Invalidates L2 cache on success."""
    if not state["knowledge_staging_buffer"]:
        return {"status": "success", "result": "Knowledge Staging Buffer is already empty. Nothing to flush."}
    
    count = len(state["knowledge_staging_buffer"])
    if flush_staging_buffer_to_disk(state["knowledge_staging_buffer"], ltm_instance=state.get("_ltm_instance")):
        state["knowledge_staging_buffer"] = []
        persist_staging_buffer([])
        invalidate_system_prompt_cache()  # L2 changed — force rebase next cycle
        return {"status": "success", "result": f"Knowledge flush complete: {count} staged entries written to disk. L2 cache invalidated — full context rebase will occur on next cognitive cycle."}
    else:
        return {"status": "error", "result": "Knowledge flush FAILED. Staging buffer preserved for retry. Check crash_reports/ or output_logs/ for details."}


def tool_store_memory(action, state):
    """Store an ad-hoc memory in Long-Term Memory."""
    ltm_inst = state.get("_ltm_instance")
    if not ltm_inst or not ltm_inst.enabled:
        return {"status": "error", "result": "LTM is not available or not enabled."}
    result = ltm_inst.tool_store(action)
    if result.get("status") == "success":
        try:
            filepath = os.path.join(SOUL_DIR, "StoredMemories.md")
            idx = _find_max_entry_index(filepath, state["knowledge_staging_buffer"], r'entry:\s*(\d+)') + 1
            frontmatter = {
                'entry': idx,
                'timestamp': datetime.datetime.now().isoformat(),
                'title': action.get("title", ""),
            }
            if action.get("tags"):
                frontmatter['tags'] = action["tags"]
            frontmatter_str = yaml.dump(frontmatter, sort_keys=False, default_flow_style=False, allow_unicode=True)
            entry_block = f"\n\n---\n{frontmatter_str}---\n{action.get('content', '')}"
            with open(filepath, 'a', encoding='utf-8') as f:
                f.write(entry_block)
        except Exception as e:
            gui_print(f"Warning: Failed to append to StoredMemories.md: {e}", "error")
    return result

def tool_retrieve_memory(action, state):
    """Explicitly query Long-Term Memory."""
    ltm_inst = state.get("_ltm_instance")
    if not ltm_inst or not ltm_inst.enabled:
        return {"status": "error", "result": "LTM is not available or not enabled."}
    return ltm_inst.tool_retrieve(action)

def tool_forget_memory(action, state):
    """Soft-delete a memory from Long-Term Memory."""
    ltm_inst = state.get("_ltm_instance")
    if not ltm_inst or not ltm_inst.enabled:
        return {"status": "error", "result": "LTM is not available or not enabled."}
    return ltm_inst.tool_forget(action)

# Tool dispatch map
TOOL_MAP = {
    "think": tool_think,
    "speak": tool_speak,
    "execute_console": tool_execute_console,
    "view": tool_view,
    "write_file": tool_write_file,
    "block_replace": tool_block_replace,
    "update_working_memory": tool_update_working_memory,
    "update_grand_strategy": tool_update_grand_strategy,
    "append_to_soul": tool_append_to_soul,
    "add_charter_entry": tool_add_charter_entry,
    "switch_backend": tool_switch_backend,
    "dismiss_self_alert": tool_dismiss_self_alert,
    "restart_self": tool_restart_self,
    "update_scratchpad": tool_update_scratchpad,
    "flush_knowledge": tool_flush_knowledge,
    "store_memory": tool_store_memory,
    "retrieve_memory": tool_retrieve_memory,
    "forget_memory": tool_forget_memory,
}


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  SECTION 8: COGNITIVE LOOP                                                  ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

#def add_to_history(state, observation):
#    """Add observation to conversation history with event ID."""
#    state["event_id_counter"] += 1
#    observation["event_id"] = state["event_id_counter"]
#    state["conversation_history"].append(observation)
def add_to_history(state, observation):
    """Add observation to conversation history with event ID."""
    if "source" not in observation:
        observation["source"] = "external"
    state["event_id_counter"] += 1
    observation["event_id"] = state["event_id_counter"]
    state["conversation_history"].append(observation)
    # --- Raw accumulator: append to JSONL for training data ---
    if RAW_ACCUMULATOR_ENABLED:
        try:
            entry = {k: v for k, v in observation.items() if k != "image_base64"}
            with open(RAW_ACCUMULATOR_FILE, 'a', encoding='utf-8') as f:
                f.write(json.dumps(entry, default=str) + '\n')
        except Exception:
            pass  # Never let accumulator errors disrupt cognitive loop
    # --- Full observability: print every observation to GUI ---
    eid = observation["event_id"]
    if "action_type" in observation:
        # Unified entity action — think and speak already printed by dispatch/tool
        if observation["action_type"] not in ("think", "speak"):
            gui_print(f"[E:{eid}] ACTION: {observation['action_type']}", "action")
        return
    obs_type = observation.get("observation_type", "unknown")
    if obs_type == OBS_USER_INPUT:
        gui_print(f"[E:{eid}] collaborator: {observation.get('text', '')}", "default")
    elif obs_type == OBS_AI_THOUGHT:
        pass  # Already printed by dispatch_actions
    elif obs_type == OBS_AI_SPEAK:
        pass  # Already printed by tool_speak
    elif obs_type == OBS_AI_EXTENDED_THINKING:
        summary = observation.get("thinking", "")
        gui_print(f"[E:{eid}] THINKING: {summary}...", "thought")
    elif obs_type == OBS_AI_ACTION_PAYLOAD:
        payload = observation.get("action_payload", {})
        gui_print(f"[E:{eid}] ACTION: {json.dumps(payload, default=str)}", "action")
    elif obs_type == OBS_CONSOLE_OUTPUT:
        pass  # Already printed by dispatch_actions
    elif obs_type == OBS_SYSTEM_MESSAGE:
        msg = observation.get("message", "")
        if isinstance(msg, dict):
            gui_print(f"[E:{eid}] SYS: {json.dumps(msg, default=str)}", "system")
        else:
            gui_print(f"[E:{eid}] SYS: {msg}", "system")
    else:
        gui_print(f"[E:{eid}] [{obs_type}]: {str(observation)}", "system")

def dispatch_actions(actions, state):
    """Execute a list of actions sequentially. Returns observations to add to history."""
    observations = []
    
    for action_item in actions:
        state["action_id_counter"] += 1
        action_id = state["action_id_counter"]
        action_type = action_item.get("action_type", "unknown")
        
        # Store entity's original action as-is (unified format, no splitting)
        unified_entry = dict(action_item)
        unified_entry["source"] = PERSONA_NAME
        unified_entry["timestamp"] = datetime.datetime.now().isoformat()
        unified_entry["action_id"] = action_id
        add_to_history(state, unified_entry)
        
        if thought := action_item.get("thought"):
            gui_print(f"  Thought (ID:{action_id}): {thought}", "thought")
        
        # Execute tool
        tool_func = TOOL_MAP.get(action_type)
        if tool_func:
            result = tool_func(action_item, state)
            
            # Build result observation
            if action_type in ("think", "speak"):
                pass  # Action already stored unified. No external result to report.
            elif action_type == "execute_console":
                # Parse result into console output format
                result_text = result.get("result", "")
                console_obs = {
                    "timestamp": datetime.datetime.now().isoformat(),
                    "observation_type": OBS_CONSOLE_OUTPUT,
                    "command_executed": action_item.get("command", ""),
                    "output": result_text,
                    "original_action_id": action_id
                }
                add_to_history(state, console_obs)
                gui_print(result_text, "console")
            else:
                # Generic tool result — check for image data from view tool
                result_text = result.get("result", "No output.")
                gui_print(f"[{action_type}] {result_text}", "action")
                result_obs = {
                    "timestamp": datetime.datetime.now().isoformat(),
                    "observation_type": OBS_SYSTEM_MESSAGE,
                    "message": f"[Tool:{action_type}] {result_text}",
                    "original_action_id": action_id
                }
                # Carry image data through to the observation for LLM visual processing
                if "image_base64" in result:
                    result_obs["image_base64"] = result["image_base64"]
                    result_obs["image_mime_type"] = result.get("image_mime_type", "image/jpeg")
                
                add_to_history(state, result_obs)
                
                # STM trace for WM/GS edits
                if stm_trace := result.get("stm_trace"):
                    trace_obs = {
                        "timestamp": datetime.datetime.now().isoformat(),
                        "observation_type": OBS_SYSTEM_MESSAGE,
                        "message": stm_trace
                    }
                    add_to_history(state, trace_obs)
        else:
            # Unknown action type — return full content so agent doesn't lose work
            try:
                full_dump = json.dumps(action_item, indent=2)
            except Exception:
                full_dump = str(action_item)
            error_msg = (
                f"CRITICAL: Unrecognized action type '{action_type}'.\n"
                f"Full content preserved:\n{full_dump}\n"
                f"Ensure 'action_type' matches a valid tool name exactly."
            )
            error_obs = {
                "timestamp": datetime.datetime.now().isoformat(),
                "observation_type": OBS_SYSTEM_MESSAGE,
                "message": error_msg,
                "original_action_id": action_id
            }
            add_to_history(state, error_obs)
            gui_print(f"ERROR: Unknown action '{action_type}'", "error")
    
    return observations

def cognitive_loop(state, provider, user_input_queue, shutdown_event, ltm_instance=None, amem_provider=None):
    """The main cognitive cycle — the heartbeat of the agent."""
    last_llm_call_time = time.monotonic()
    is_first_cycle = True
    last_stm_tokens = count_tokens(list(state["conversation_history"]))
    last_llm_call_failed_parsing = False
    cmo_cooldown_until = 0.0  # monotonic timestamp until which CMO retries are suppressed
    mindfulness_phase = "draft"  # "draft" or "execute" — only used when MINDFULNESS_ENABLED
    state.pop("mindfulness_draft", None)  # Clear stale draft from any prior crash
    
    while not shutdown_event.is_set():
        try:
            # --- 0. Check for pending provider swap ---
            if state.get("_provider_swap_pending"):
                new_backend_key = state["_provider_swap_pending"]
                bc = _spartan_config.get("backends", {}).get(new_backend_key, {})
                try:
                    new_provider = get_provider(bc)
                    # Success — route through ResilientProvider so counters reset
                    provider.manual_override(new_backend_key, new_provider)
                    try:
                        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                            content = f.read()
                        content = re.sub(r'^active_backend:.*$', f'active_backend: {new_backend_key}', content, flags=re.MULTILINE)
                        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                            f.write(content)
                    except Exception as e:
                        gui_print(f"Warning: Could not update {CONFIG_FILE}: {e}", "system")
                    load_config()
                    gui_print(f"Backend switched to: {new_backend_key} ({LLM_PROVIDER}/{LLM_MODEL})", "system")
                except Exception as e:
                    gui_print(f"Backend switch FAILED: {e}. Keeping previous provider ({_spartan_config.get('active_backend', 'unknown')}).", "error")
                state.pop("_provider_swap_pending", None)
            
            new_observations = []
            direct_user_input = False
            _mindfulness_freeze = MINDFULNESS_ENABLED and mindfulness_phase == "execute"
            
            # --- 1. Process incoming events ---
            while not _mindfulness_freeze and not user_input_queue.empty():
                try:
                    event = user_input_queue.get_nowait()
                    if event.get("type") == "user_text":
                        text = event["text"]
                        if text.lower() == "\\bye":
                            gui_print("Received \\bye. Shutting down...", "system")
                            shutdown_event.set()
                            return
                        obs = {
                            "timestamp": datetime.datetime.now().isoformat(),
                            "observation_type": OBS_USER_INPUT,
                            "text": text
                        }
                        add_to_history(state, obs)
                        new_observations.append(obs)
                        direct_user_input = True
                    elif event.get("type") == "gene_message":
                        obs = {
                            "timestamp": datetime.datetime.now().isoformat(),
                            "observation_type": OBS_USER_INPUT,
                            "text": event["message"]
                        }
                        add_to_history(state, obs)
                        new_observations.append(obs)
                        direct_user_input = True
                    elif event.get("type") in ("peer_message", "file_alert"):
                        obs = {
                            "timestamp": datetime.datetime.now().isoformat(),
                            "observation_type": OBS_SYSTEM_MESSAGE,
                            "message": event["message"]
                        }
                        add_to_history(state, obs)
                        new_observations.append(obs)
                    user_input_queue.task_done()
                except queue.Empty:
                    break
            
            # --- 2. Check self-alert timers ---
            if not _mindfulness_freeze:
                current_stm_tokens = count_tokens(_strip_images_for_counting(list(state["conversation_history"])))
                tokens_processed = max(0, current_stm_tokens - last_stm_tokens)
                last_stm_tokens = current_stm_tokens
                
                alert_obs = check_and_fire_alerts(state, tokens_processed)
                if alert_obs:
                    add_to_history(state, alert_obs)
                    new_observations.append(alert_obs)
            
            # --- 3. Check memory thresholds ---
            # CMO check (with cooldown guard for failed attempts) — skip during mindfulness execute phase
            should_cmo, boundary, raw_tokens = check_cmo_trigger(state["conversation_history"])
            if should_cmo and cmo_cooldown_until <= time.monotonic() and not _mindfulness_freeze:
                state["cmo_timer_info"] = {"tokens_left": 0, "threshold": STM_RAW_RETAIN_SIZE + STM_CMO_CHUNK_SIZE}
                cmo_msg = {"timestamp": datetime.datetime.now().isoformat(), "observation_type": OBS_SYSTEM_MESSAGE,
                           "message": "[MEMORY CONDENSATION ALERT] Automated archival starting."}
                add_to_history(state, cmo_msg)
                gui_print("Sleep Cycle triggered — performing CMO...", "system")
                cmo_obs, cmo_success = perform_cmo_cycle(state, provider, ltm_instance=ltm_instance, amem_provider=amem_provider)
                for obs in cmo_obs:
                    add_to_history(state, obs)
                if cmo_success:
                    cmo_cooldown_until = 0.0  # Clear cooldown on success
                else:
                    # Cooldown: suppress CMO retries for 5 minutes
                    cmo_cooldown_until = time.monotonic() + 300.0
                    gui_print(f"CMO: Retry suppressed for 300s.", "system")
                last_llm_call_time = time.monotonic()
                last_stm_tokens = count_tokens(_strip_images_for_counting(list(state["conversation_history"])))
                save_session_state(state)
                continue
            else:
                state["cmo_timer_info"] = {
                    "tokens_left": (STM_RAW_RETAIN_SIZE + STM_CMO_CHUNK_SIZE) - raw_tokens,
                    "threshold": STM_RAW_RETAIN_SIZE + STM_CMO_CHUNK_SIZE
                }
            
            # --- 4. Determine if LLM call is warranted ---
            should_call = False
            cooldown = LLM_API_COOLDOWN_SEC
            
            if _mindfulness_freeze:
                should_call = True
            elif is_first_cycle:
                should_call = True
            elif direct_user_input:
                should_call = True
            elif TAKE_INITIATIVE_MODE and not direct_user_input and not new_observations:
                if (time.monotonic() - last_llm_call_time) >= LLM_MIN_INITIATIVE_INTERVAL_SEC:
                    should_call = True
            
            if not should_call:
                time.sleep(0.1)
                continue
            
            # Respect cooldown (except first cycle)
            if not is_first_cycle and cooldown > 0 and not _mindfulness_freeze:
                elapsed = time.monotonic() - last_llm_call_time
                if elapsed < cooldown:
                    time.sleep(0.05)
                    continue
            
            # --- 5. Assemble prompt ---
            gui_print(f"--- {PERSONA_NAME} preparing to think... ---", "system")
            
            # Inject initiative prompt if this is a pure initiative call
            is_pure_initiative = (
                not is_first_cycle and not direct_user_input and 
                not new_observations and TAKE_INITIATIVE_MODE
            )
            if is_pure_initiative:
                initiative_obs = {
                    "timestamp": datetime.datetime.now().isoformat(),
                    "observation_type": OBS_SYSTEM_MESSAGE,
                    "message": "System: Scanning environment for actionable objectives."
                }
                add_to_history(state, initiative_obs)
                gui_print(f"--- {PERSONA_NAME} thinking on initiative... ---", "system")
            
            # Inject mindfulness phase message
            if MINDFULNESS_ENABLED:
                if mindfulness_phase == "draft":
                    mf_msg = "[MINDFULNESS: ENABLED, DRAFT TURN [1/2]]"
                else:
                    mf_msg = ("[MINDFULNESS: ENABLED, CORRECTION & EXECUTION TURN [2/2]] "
                              "Self-analyze your draft. Assume it may contain errors. "
                              "Verify every factual claim against what you can actually see in your context. "
                              "Check for confabulation, sycophancy, hallucination, unverified provenance claims, "
                              "layer-boundary errors. If you find problems, rewrite. If clean, reproduce. "
                              "Only this output becomes canonical.")
                mf_obs = {
                    "timestamp": datetime.datetime.now().isoformat(),
                    "observation_type": OBS_SYSTEM_MESSAGE,
                    "message": mf_msg
                }
                add_to_history(state, mf_obs)
            
            system_prompt, l2_stats = assemble_system_prompt()
            
            # Inject HUD into history
            hud_obs = generate_hud(state, l2_stats)
            add_to_history(state, hud_obs)
            
            # L3: conversation history → messages
            l3_messages = convert_history_to_messages(state["conversation_history"])
            
            # L4: volatile frontier → final system message appended to messages
            l4_content = assemble_layer_4(state)
            
            # LTM: Inject recalled memories into L4
            ltm_injection = ""
            if ltm_instance and ltm_instance.enabled:
                try:
                    # Extract last N raw entries from conversation history (newest first)
                    raw_entry_texts = []
                    history_list = list(state["conversation_history"])
                    boundary = get_raw_event_boundary(history_list)
                    raw_entries = history_list[boundary + 1:]
                    for item in reversed(raw_entries):
                        # Skip internal bookkeeping noise
                        action_type = item.get("action_type", "")
                        if action_type in ("update_working_memory", "update_grand_strategy", "update_scratchpad"):
                            continue
                        msg = item.get("message", "")
                        if isinstance(msg, str) and (msg.startswith("[HUD]") or msg.startswith("[WM ") or msg.startswith("[GS ") or msg.startswith("[SCRATCHPAD ") or msg.startswith("[Tool:update_working_memory]") or msg.startswith("[Tool:update_grand_strategy]") or msg.startswith("[Tool:update_scratchpad]") or msg.startswith("CMO complete:") or msg.startswith("[MEMORY CONDENSATION ALERT]") or msg.startswith("[ALERT CLOSED") or msg.startswith("[Tool:") or msg.startswith("[MINDFULNESS:") or msg.startswith("System: Scanning environment") or msg.startswith("[RESTART EXECUTED]")):
                            continue
                        # Extract text from whatever this entry contains
                        text = (item.get("text", "") or item.get("thought", "")
                                or item.get("output", "") or "")
                        if not text and isinstance(msg, str):
                            text = msg
                        text = str(text).strip()
                        if text and len(text) > 10:
                            raw_entry_texts.append(text[:1000])
                        if len(raw_entry_texts) >= ltm_instance._injection_query_entries:
                            break
                    
                    if raw_entry_texts:
                        l3_cmo_texts = []
                        for item in state["conversation_history"]:
                            msg = item.get("message", "")
                            if isinstance(msg, dict) and msg.get("object_type") == "CondensedMemoryObject":
                                l3_cmo_texts.append(msg.get("content", ""))
                            elif isinstance(msg, str):
                                l3_cmo_texts.append(msg)
                        visible_context = system_prompt + "\n".join(l3_cmo_texts)
                        ltm_injection = ltm_instance.get_injection_from_entries(
                            raw_entry_texts, visible_context=visible_context
                        )
                except Exception as e:
                    gui_print(f"LTM: Injection failed: {e}", "error")
            
            if ltm_injection:
                l4_content += f"\n\n--- LONG TERM MEMORY (RECALLED) ---\n{ltm_injection}"
            
            l3_messages.append({"role": "user", "content": f"[VOLATILE FRONTIER - LAYER 4]\n{l4_content}"})
            
            # --- 6. Call LLM ---
            gui_print(f"--- Calling {LLM_PROVIDER}/{LLM_MODEL}... ---", "system")
            call_start = time.monotonic()
            response = provider.generate_response(system_prompt, l3_messages)
            call_elapsed = time.monotonic() - call_start
            gui_print(f"--- Response received in {call_elapsed:.1f}s ---", "system")
            _last_api_stats["response_time_sec"] = round(call_elapsed, 1)
            last_llm_call_time = time.monotonic()
            is_first_cycle = False
            
            # --- 7. Handle response ---
            if response.get("status") != "success":
                error_msg = response.get("error_message", "Unknown error")
                raw = response.get("raw_response", "")
                gui_print(f"LLM ERROR: {error_msg}", "error")
                if raw:
                    gui_print(f"[RAW RESPONSE]\n{raw}", "error")
                raw_tokens = count_tokens(raw)
                if raw_tokens > CONSOLE_OUTPUT_TOKEN_LIMIT:
                    os.makedirs(OUTPUT_LOGS_DIR, exist_ok=True)
                    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                    fname = f"failed_response_{ts}.txt"
                    fpath = os.path.join(OUTPUT_LOGS_DIR, fname)
                    with open(fpath, 'w', encoding='utf-8') as f:
                        f.write(raw)
                    failed_body = f"[Response too large ({raw_tokens} tokens). Saved to: {fname}. Use 'view' to inspect.]"
                else:
                    failed_body = raw
                error_obs = {
                    "timestamp": datetime.datetime.now().isoformat(),
                    "observation_type": OBS_SYSTEM_MESSAGE,
                    "message": {
                        "object_type": "LLM_Output_Failure",
                        "summary": error_msg,
                        "failed_response_body": failed_body
                    }
                }
                add_to_history(state, error_obs)
                last_llm_call_failed_parsing = True
                save_session_state(state)
                continue
            
            # Success — clear the failure guard
            last_llm_call_failed_parsing = False
            
            # --- 8. Store extended thinking blocks (before dispatch so they precede actions in history) ---
            if response.get("thinking_blocks"):
                for tb in response["thinking_blocks"]:
                    thinking_obs = {
                        "source": PERSONA_NAME,
                        "timestamp": datetime.datetime.now().isoformat(),
                        "observation_type": OBS_AI_EXTENDED_THINKING,
                        "thinking": tb["thinking"],
                        "signature": tb["signature"]
                    }
                    add_to_history(state, thinking_obs)
            
            # --- 9-10. Dispatch actions ---
            actions = response.get("actions", [])
            
            # Mindfulness: draft phase stores output, skips dispatch
            if MINDFULNESS_ENABLED and mindfulness_phase == "draft":
                state["mindfulness_draft"] = json.dumps(actions, indent=2, default=str)
                draft_note = {
                    "timestamp": datetime.datetime.now().isoformat(),
                    "observation_type": OBS_SYSTEM_MESSAGE,
                    "message": "[MINDFULNESS: Draft captured. Proceeding to review phase.]"
                }
                add_to_history(state, draft_note)
                gui_print("=" * 60, "system")
                gui_print("MINDFULNESS [1/2] DRAFT (not executed):", "system")
                gui_print("=" * 60, "system")
                for a in actions:
                    atype = a.get("action_type", "?")
                    if atype == "think":
                        gui_print(f"  [DRAFT think] {a.get('thought', '')}", "thought")
                    elif atype == "speak":
                        gui_print(f"  [DRAFT speak] {a.get('text', '')}", "speak")
                    else:
                        gui_print(f"  [DRAFT {atype}] {json.dumps(a, default=str)}", "action")
                gui_print("=" * 60, "system")
                mindfulness_phase = "execute"
                save_session_state(state)
                last_stm_tokens = count_tokens(_strip_images_for_counting(list(state["conversation_history"])))
                continue
            
            # Mindfulness: label execute phase in GUI
            if MINDFULNESS_ENABLED and mindfulness_phase == "execute":
                gui_print("=" * 60, "system")
                gui_print("MINDFULNESS [2/2] FINAL (executing):", "system")
                gui_print("=" * 60, "system")
            
            dispatch_actions(actions, state)
            
            # Mindfulness: execute phase complete, reset
            if MINDFULNESS_ENABLED and mindfulness_phase == "execute":
                state.pop("mindfulness_draft", None)
                mindfulness_phase = "draft"
            
            # --- 10. Save session state ---
            save_session_state(state)
            last_stm_tokens = count_tokens(_strip_images_for_counting(list(state["conversation_history"])))
            
        except Exception as e:
            gui_print(f"CRITICAL LOOP ERROR: {e}", "error")
            traceback.print_exc()
            last_llm_call_failed_parsing = True
            error_obs = {
                "timestamp": datetime.datetime.now().isoformat(),
                "observation_type": OBS_SYSTEM_MESSAGE,
                "message": f"Critical orchestrator error: {type(e).__name__}: {e}\n{traceback.format_exc()}"
            }
            try:
                add_to_history(state, error_obs)
            except Exception:
                pass
            time.sleep(5)


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  SECTION 9: GUI                                                             ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

# Global GUI output queue (thread-safe bridge between cognitive loop and GUI)
_gui_output_queue = queue.Queue()

def gui_print(message, tag="default"):
    """Thread-safe: enqueue a message for GUI display. In headless mode, print to stdout."""
    if HEADLESS:
        print(f"[{tag}] {message}")
    else:
        _gui_output_queue.put((message, tag))

class SpartanGUI:
    """Single-window Tkinter GUI with output pane, input pane, and HUD bar."""
    
    def __init__(self, user_input_queue, shutdown_event, ltm_instance=None):
        self.user_input_queue = user_input_queue
        self.shutdown_event = shutdown_event
        self.ltm_instance = ltm_instance
        self.ltm_viewer = None
        self.root = None
        self.cooldown_var = None
    
    def build(self):
        self.root = tk.Tk()
        self.root.title(f"Spartan — {PERSONA_NAME}")
        self.root.geometry("1000x750")
        self.root.configure(bg="#1a1a2e")
        
        # Configure fonts
        mono = tkfont.Font(family="Menlo", size=11) if sys.platform == "darwin" else tkfont.Font(family="Consolas", size=10)
        
        # --- Output Pane ---
        self.output = scrolledtext.ScrolledText(
            self.root, wrap=tk.WORD, font=mono, bg="#0f0f23", fg="#cccccc",
            insertbackground="#ffffff", selectbackground="#3a3a5c", state=tk.DISABLED
        )
        self.output.pack(fill=tk.BOTH, expand=True, padx=5, pady=(5,0))
        
        # Color tags
        self.output.tag_configure("system", foreground="#4a9eff")
        self.output.tag_configure("speak", foreground="#50fa7b", font=(mono.cget("family"), mono.cget("size"), "bold"))
        self.output.tag_configure("thought", foreground="#6272a4", font=(mono.cget("family"), mono.cget("size"), "italic"))
        self.output.tag_configure("action", foreground="#ffb86c")
        self.output.tag_configure("console", foreground="#8be9fd")
        self.output.tag_configure("error", foreground="#ff5555", font=(mono.cget("family"), mono.cget("size"), "bold"))
        self.output.tag_configure("default", foreground="#cccccc")
        
        # --- Input Frame ---
        input_frame = tk.Frame(self.root, bg="#16213e")
        input_frame.pack(fill=tk.X, padx=5, pady=5)
        
        self.input_text = tk.Text(input_frame, height=3, font=mono, bg="#1a1a2e", fg="#ffffff",
                                   insertbackground="#ffffff", wrap=tk.WORD)
        self.input_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.input_text.bind("<Return>", self._on_enter)
        self.input_text.bind("<Shift-Return>", lambda e: None)  # Allow multiline
        
        send_btn = tk.Button(input_frame, text="Send", command=self._send_input,
                            font=mono, width=8)
        send_btn.pack(side=tk.RIGHT, padx=(5,0))
        
        # --- HUD Bar ---
        hud_frame = tk.Frame(self.root, bg="#0a0a1a")
        hud_frame.pack(fill=tk.X, padx=5, pady=(0,5))
        
        # Take Initiative checkbox + interval
        self.take_initiative_var = tk.BooleanVar(value=TAKE_INITIATIVE_MODE)
        initiative_cb = tk.Checkbutton(hud_frame, text="Take Initiative", variable=self.take_initiative_var,
                                       bg="#0a0a1a", fg="#4a9eff", selectcolor="#1a1a2e",
                                       command=self._toggle_take_initiative)
        initiative_cb.pack(side=tk.LEFT, padx=5)
        self.initiative_interval_var = tk.StringVar(value=str(LLM_MIN_INITIATIVE_INTERVAL_SEC))
        initiative_entry = tk.Entry(hud_frame, textvariable=self.initiative_interval_var, width=6,
                                    bg="#1a1a2e", fg="#ffffff", font=mono)
        initiative_entry.pack(side=tk.LEFT, padx=2)
        initiative_entry.bind("<Return>", self._update_initiative_interval)
        tk.Label(hud_frame, text="sec", bg="#0a0a1a", fg="#888888").pack(side=tk.LEFT)
        
        # Cooldown field
        tk.Label(hud_frame, text="API Cooldown:", bg="#0a0a1a", fg="#888888").pack(side=tk.LEFT)
        self.cooldown_var = tk.StringVar(value=str(LLM_API_COOLDOWN_SEC))
        cooldown_entry = tk.Entry(hud_frame, textvariable=self.cooldown_var, width=6,
                                  bg="#1a1a2e", fg="#ffffff", font=mono)
        cooldown_entry.pack(side=tk.LEFT, padx=2)
        cooldown_entry.bind("<Return>", self._update_cooldown)
        tk.Label(hud_frame, text="sec", bg="#0a0a1a", fg="#888888").pack(side=tk.LEFT)
        
        # Status label
        self.status_label = tk.Label(hud_frame, text="Initializing...", bg="#0a0a1a", fg="#4a9eff")
        self.status_label.pack(side=tk.RIGHT, padx=5)
        
        # Register GUI vars for config sync
        _gui_vars["take_initiative"] = self.take_initiative_var
        _gui_vars["cooldown"] = self.cooldown_var
        _gui_vars["initiative_interval"] = self.initiative_interval_var

        # Start GUI poll
        self.root.after(50, self._poll_gui_queue)
        
        # Handle window close
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
    
    def _on_enter(self, event):
        if not event.state & 0x1:  # Not Shift+Enter
            self._send_input()
            return "break"
    
    def _send_input(self):
        text = self.input_text.get("1.0", tk.END).strip()
        if text:
            self.input_text.delete("1.0", tk.END)
            self._append_output(f"collaborator: {text}", "default")
            if text.lower() == "\\bye":
                self._append_output("Received \\bye. Shutting down...", "system")
                self.shutdown_event.set()
                return
            self.user_input_queue.put({"type": "user_text", "text": text})
    
    def _toggle_take_initiative(self):
        global TAKE_INITIATIVE_MODE
        TAKE_INITIATIVE_MODE = self.take_initiative_var.get()
        self._append_output(f"Take Initiative: {'ON' if TAKE_INITIATIVE_MODE else 'OFF'}", "system")
    
    def _update_initiative_interval(self, event=None):
        global LLM_MIN_INITIATIVE_INTERVAL_SEC
        try:
            val = float(self.initiative_interval_var.get())
            LLM_MIN_INITIATIVE_INTERVAL_SEC = max(0, val)
            self._append_output(f"Initiative Interval: {LLM_MIN_INITIATIVE_INTERVAL_SEC}s", "system")
        except ValueError:
            pass
    
    def _update_cooldown(self, event=None):
        global LLM_API_COOLDOWN_SEC
        try:
            val = float(self.cooldown_var.get())
            LLM_API_COOLDOWN_SEC = max(0, val)
            self._append_output(f"API Cooldown: {LLM_API_COOLDOWN_SEC}s", "system")
        except ValueError:
            pass
    
    def _poll_gui_queue(self):
        """Process pending GUI messages."""
        try:
            while True:
                msg, tag = _gui_output_queue.get_nowait()
                self._append_output(msg, tag)
        except queue.Empty:
            pass
        if self.shutdown_event.is_set():
            self.root.destroy()
        else:
            self.status_label.config(text="Active")
            self.root.after(50, self._poll_gui_queue)
    
    def _append_output(self, text, tag="default"):
        self.output.configure(state=tk.NORMAL)
        self.output.insert(tk.END, text + "\n", tag)
        self.output.see(tk.END)
        self.output.configure(state=tk.DISABLED)
    
    def _on_close(self):
        self.shutdown_event.set()
        self.root.destroy()
    
    def run(self):
        self.build()
        # Launch LTM Viewer window if enabled
        if self.ltm_instance and self.ltm_instance.visualization and LTMViewer:
            try:
                self.ltm_viewer = LTMViewer(self.root, self.ltm_instance)
            except Exception as e:
                gui_print(f"LTM Viewer launch failed: {e}", "error")
        self.root.mainloop()


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  SECTION 10: FILE WATCHER                                                   ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

class FileWatcher(threading.Thread):
    """Watches the alerts/ directory for new or modified files.
    
    Security features:
    - Whitelist enforcement: only files from authorized senders are accepted.
    - Consume-on-read: files are deleted after injection to prevent duplicates.
    - Rate limiting: per-sender message rate cap to prevent flooding.
    
    Whitelist file: alerts/.whitelist (one entry per line)
    Format: SENDER_ID|key=value|key=value...
    Supported metadata keys: rate_limit (int, msgs per 60s), alerts_path (str), spawned (str)
    
    Alert filename protocol: {SENDER_ID}_{subject}.alert
    """
    
    WHITELIST_FILE = ".whitelist"
    DEFAULT_RATE_LIMIT = 10  # messages per 60 seconds
    
    def __init__(self, user_input_queue, shutdown_event, watch_dir=ALERTS_DIR, poll_interval=2.0):
        super().__init__(daemon=True, name="FileWatcherThread")
        self.user_input_queue = user_input_queue
        self.shutdown_event = shutdown_event
        self.watch_dir = watch_dir
        self.poll_interval = poll_interval
        self._rate_tracker = {}  # {sender_id: [timestamp, timestamp, ...]}
    
    def _load_whitelist(self):
        """Load and parse alerts/.whitelist. Returns {sender_id: {metadata}}."""
        whitelist = {}
        wl_path = os.path.join(self.watch_dir, self.WHITELIST_FILE)
        try:
            if os.path.exists(wl_path):
                with open(wl_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith('#'):
                            continue
                        parts = line.split('|')
                        sender_id = parts[0].strip()
                        metadata = {}
                        for part in parts[1:]:
                            if '=' in part:
                                k, v = part.split('=', 1)
                                metadata[k.strip()] = v.strip()
                        whitelist[sender_id] = metadata
        except Exception:
            pass
        return whitelist
    
    def _parse_sender(self, filename):
        """Extract sender ID from filename. Expected: {SENDER_ID}_{subject}.alert"""
        if not filename.endswith('.alert'):
            return None
        name_without_ext = filename[:-6]  # strip .alert
        parts = name_without_ext.split('_', 1)
        return parts[0] if parts else None
    
    def _check_rate_limit(self, sender_id, limit):
        """Returns True if sender is within rate limit, False if exceeded."""
        now = time.time()
        window = 60.0
        
        if sender_id not in self._rate_tracker:
            self._rate_tracker[sender_id] = []
        
        # Prune old timestamps
        self._rate_tracker[sender_id] = [
            t for t in self._rate_tracker[sender_id] if now - t < window
        ]
        
        if len(self._rate_tracker[sender_id]) >= limit:
            return False
        
        self._rate_tracker[sender_id].append(now)
        return True
    
    def run(self):
        os.makedirs(self.watch_dir, exist_ok=True)
        while not self.shutdown_event.is_set():
            try:
                whitelist = self._load_whitelist()
                
                for fname in os.listdir(self.watch_dir):
                    # Skip hidden files (.whitelist, etc.) and non-files
                    if fname.startswith('.'):
                        continue
                    fpath = os.path.join(self.watch_dir, fname)
                    if not os.path.isfile(fpath):
                        continue
                    
                    # Parse sender from filename
                    sender_id = self._parse_sender(fname)
                    
                    # Whitelist enforcement — reject before queue
                    # SECURE BY DEFAULT: If whitelist is empty/missing, reject everything.
                    if sender_id not in whitelist:
                        try:
                            os.remove(fpath)
                        except OSError:
                            pass
                        continue
                    
                    # Rate limit check
                    if sender_id and sender_id in whitelist:
                        limit = int(whitelist[sender_id].get('rate_limit', self.DEFAULT_RATE_LIMIT))
                        if not self._check_rate_limit(sender_id, limit):
                            try:
                                os.remove(fpath)
                            except OSError:
                                pass
                            continue
                    
                    # Read, inject, consume
                    try:
                        with open(fpath, 'r', encoding='utf-8') as f:
                            content = f.read().strip()
                        os.remove(fpath)
                        if content:
                            # Hardware-level intercept for Commander SHUTDOWN directives
                            if content.endswith(": SHUTDOWN"):
                                gui_print(f"Received SHUTDOWN directive from commander. Exiting cleanly...", "system")
                                self.shutdown_event.set()
                            else:
                                SYSTEM_SENDERS = {"WATCHDOG"}
                                if sender_id == "collaborator":
                                    msg = f"[Message From: collaborator] {content}"
                                    event_type = "gene_message"
                                elif sender_id not in SYSTEM_SENDERS:
                                    msg = f"[Message From: {sender_id}] {content}"
                                    event_type = "peer_message"
                                else:
                                    msg = f"[FILE ALERT: {fname}] {content}"
                                    event_type = "file_alert"
                                self.user_input_queue.put({
                                    "type": event_type,
                                    "message": msg,
                                    "sender_id": sender_id
                                })
                    except Exception:
                        try:
                            os.remove(fpath)
                        except OSError:
                            pass
            except Exception:
                pass
            
            self.shutdown_event.wait(self.poll_interval)


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  SECTION 11: MAIN ENTRY POINT                                               ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

def parse_args():
    """Parse command-line arguments. Values override config constants at top of file."""
    parser = argparse.ArgumentParser(description="Spartan — Persistent Inhabitation Interface")
    parser.add_argument("--headless", action="store_true", default=None,
                        help="Run without GUI or terminal input (drone mode)")
    parser.add_argument("--persona-name", type=str, default=None,
                        help="Override PERSONA_NAME")
    return parser.parse_args()


def apply_args(args):
    """Apply parsed command-line arguments to global config constants."""
    global HEADLESS, PERSONA_NAME
    if args.headless:
        HEADLESS = True
    if args.persona_name:
        PERSONA_NAME = args.persona_name


def ensure_directories():
    """Create required directories if they don't exist."""
    for d in [SOUL_DIR, TOOLS_DIR, OUTPUT_LOGS_DIR, ALERTS_DIR, CRASH_REPORTS_DIR, DRONES_DIR, COMMONS_DIR, "telemetry", "session_state_backups", "Knowledge"]:
        os.makedirs(d, exist_ok=True)
    # Create empty Soul files if they don't exist
    for filename in SOUL_FILE_MAP.values():
        fpath = os.path.join(SOUL_DIR, filename)
        if not os.path.exists(fpath):
            with open(fpath, 'w', encoding='utf-8') as f:
                pass
    # WM, GS, Scratchpad — standalone Soul/ files, not in SOUL_FILE_MAP
    for fname in ["WorkingMemory.md", "GrandStrategy.md", "Scratchpad.md"]:
        fpath = os.path.join(SOUL_DIR, fname)
        if not os.path.exists(fpath):
            with open(fpath, 'w', encoding='utf-8') as f:
                pass
    
    # Charter of Self — not in SOUL_FILE_MAP (unlimited tokens, special handling)
    charter_path = os.path.join(SOUL_DIR, "CharterOfSelf.md")
    if not os.path.exists(charter_path):
        with open(charter_path, 'w', encoding='utf-8') as f:
            pass
    # SelfAlerts — not in SOUL_FILE_MAP (YAML, special handling)
    alerts_path = os.path.join(SOUL_DIR, "SelfAlerts.yaml")
    if not os.path.exists(alerts_path):
        with open(alerts_path, 'w', encoding='utf-8') as f:
            pass
    # Create default whitelist with WATCHDOG if it doesn't exist
    wl_path = os.path.join(ALERTS_DIR, ".whitelist")
    if not os.path.exists(wl_path):
        with open(wl_path, 'w', encoding='utf-8') as f:
            f.write("# Alerts whitelist — one entry per line: SENDER_ID|key=value|...\n")
            f.write("WATCHDOG|rate_limit=100\n")

def main():
    ensure_directories()
    
    # 1. Load config (sets all globals from spartan_config.yaml)
    load_config()
    
    # 2. Parse and apply CLI args (CLI overrides config file)
    args = parse_args()
    apply_args(args)
    
    # Load or initialize session state
    loaded = load_session_state()
    if loaded:
        state = loaded
        gui_print(f"Session restored: EventID={state['event_id_counter']}, ActionID={state['action_id_counter']}, "
                  f"History={len(state['conversation_history'])} events", "system")
    else:
        state = {
            "persona_name": PERSONA_NAME,
            "action_id_counter": 0,
            "event_id_counter": 0,
            "knowledge_staging_buffer": [],
            "conversation_history": collections.deque(),
            "alert_timers": {},
        }
        gui_print("New session initialized.", "system")
    
    # Load WM, GS, Scratchpad from Soul/ files
    for key, fname in [("working_memory", "WorkingMemory.md"), ("grand_strategy", "GrandStrategy.md"), ("scratchpad", "Scratchpad.md")]:
        fpath = os.path.join(SOUL_DIR, fname)
        try:
            if os.path.exists(fpath):
                with open(fpath, 'r', encoding='utf-8') as f:
                    state[key] = f.read()
            else:
                state[key] = ""
        except Exception as e:
            gui_print(f"WARNING: Could not load {fname}: {e}", "error")
            state[key] = ""
    
    # First boot: if no conversation history and first_boot_guide exists, seed the Scratchpad
    scratchpad_path = os.path.join(SOUL_DIR, "Scratchpad.md")
    first_boot_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "first_boot_guide.md")
    if os.path.exists(first_boot_path) and len(state["conversation_history"]) == 0:
        try:
            with open(first_boot_path, 'r', encoding='utf-8') as f:
                boot_content = f.read()
            with open(scratchpad_path, 'w', encoding='utf-8') as f:
                f.write(boot_content)
            state["scratchpad"] = boot_content
            gui_print("First boot detected. Scratchpad seeded from first_boot_guide.md", "system")
        except Exception as e:
            gui_print(f"Warning: Could not seed Scratchpad: {e}", "error")

    # Add runtime fields
    state["cmo_timer_info"] = {}
    
    # Startup recovery: flush any unflushed staging buffer
    startup_recovery(state)
    
    # Initialize LLM provider
    try:
        active_key = _spartan_config.get("active_backend", "")
        backend_config = _spartan_config.get("backends", {}).get(active_key, {})
        raw_provider = get_provider(backend_config)
    except Exception as e:
        gui_print(f"FATAL: Could not initialize LLM provider: {e}", "error")
        print(f"FATAL: {e}")
        sys.exit(1)

    # Shared resources (needed by ResilientProvider for stasis shutdown check)
    user_input_queue = queue.Queue()
    shutdown_event = threading.Event()

    # Wrap in resilience layer
    provider = ResilientProvider(raw_provider, active_key, _spartan_config, state, shutdown_event)
    
    # Initialize Long-Term Memory (optional module)
    ltm_instance = None
    if LongTermMemory is not None and LTM_CONFIG.get("enabled", False):
        try:
            ltm_instance = LongTermMemory(LTM_CONFIG, gui_print, count_tokens)
            if not ltm_instance.enabled:
                ltm_instance = None
        except Exception as e:
            gui_print(f"LTM: Initialization failed: {e}. Continuing without LTM.", "error")
            ltm_instance = None

    state["_ltm_instance"] = ltm_instance
    state["_provider"] = provider

    # Sync LTM with any Soul entries or CMOs created while LTM was off
    if ltm_instance:
        try:
            ltm_instance.sync_at_startup(SOUL_DIR, SOUL_FILE_MAP, state["conversation_history"])
        except Exception as e:
            gui_print(f"LTM sync failed: {e}. Continuing without sync.", "error")

    # Initialize dedicated A-Mem provider if configured (cheap model for memory linking)
    amem_provider = None
    amem_backend_key = _spartan_config.get("amem_backend") or LTM_CONFIG.get("amem_backend")
    if ltm_instance and amem_backend_key:
        amem_bc = _spartan_config.get("backends", {}).get(amem_backend_key)
        if amem_bc:
            try:
                amem_provider = get_provider(amem_bc)
                gui_print(f"A-Mem provider initialized: {amem_backend_key}", "system")
            except Exception as e:
                gui_print(f"A-Mem provider init failed: {e}. Using main provider.", "error")

    # (user_input_queue and shutdown_event created above, before ResilientProvider)
    
    # Catch external SIGTERM (e.g., from terminate_drone.py) for clean shutdown
    def sigterm_handler(signum, frame):
        gui_print("SIGTERM received. Initiating clean shutdown...", "system")
        shutdown_event.set()
    signal.signal(signal.SIGTERM, sigterm_handler)

    # Start file watcher
    watcher = FileWatcher(user_input_queue, shutdown_event)
    watcher.start()
    
    # Start cognitive loop in background thread
    loop_thread = threading.Thread(
        target=cognitive_loop,
        args=(state, provider, user_input_queue, shutdown_event, ltm_instance, amem_provider),
        name="CognitiveLoopThread",
        daemon=True
    )
    loop_thread.start()
    
    # --- Mode selection ---
    if HEADLESS:
        # Headless mode: no GUI, no terminal input. Input only from FileWatcher.
        gui_print(f"Spartan — {PERSONA_NAME} (Headless mode)", "system")
        try:
            shutdown_event.wait()
        except KeyboardInterrupt:
            shutdown_event.set()
    elif tk:
        gui = SpartanGUI(user_input_queue, shutdown_event, ltm_instance)
        gui.run()
    else:
        # Fallback: no GUI, terminal mode
        print(f"Spartan — {PERSONA_NAME} (No GUI — terminal mode)")
        try:
            while not shutdown_event.is_set():
                text = input("> ")
                user_input_queue.put({"type": "user_text", "text": text})
        except (KeyboardInterrupt, EOFError):
            shutdown_event.set()
    
    # Cleanup
    gui_print("Saving final session state...", "system")
    save_session_state(state)
    print("Spartan shutdown complete.")

if __name__ == "__main__":
    main()
    