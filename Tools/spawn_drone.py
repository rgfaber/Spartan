#!/usr/bin/env python3
"""
spawn_drone.py — Spawns a new Spartan drone instance.

Usage:
    python Tools/spawn_drone.py \
        --name DRONE-ALPHA \
        --mission "Review all Python files in auth/ for SQL injection vulnerabilities" \
        --backend gemini_flash \
        [--identity "You are a meticulous security auditor who leaves no stone unturned."]

Called by the commander via execute_console. Creates the drone directory inside
the commander's drones/ folder, writes the Charter, sets up whitelists, and starts
the watchdog.

Output: Prints drone ID, PID, and directory path on success.
"""

import argparse
import os
import sys
import shutil
import subprocess
import datetime
import yaml


def get_commander_dir():
    """Resolve the commander's Spartan root directory."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def generate_charter(name, mission, commander_name, commander_alerts_path, identity=None):
    """Generate a CharterOfSelf.md for the drone."""
    identity_section = ""
    if identity:
        identity_section = f"""
## Identity
{identity}
"""

    return f"""# Charter of Self — {name}

## Designation
- **ID:** {name}
- **Type:** Drone
- **Commander:** {commander_name}
- **Commander Alerts Path:** {commander_alerts_path}
- **Spawned:** {datetime.datetime.now().isoformat()}

## Mission
{mission}
{identity_section}
## Operating Protocol
- Report progress and findings to your commander by writing to: {commander_alerts_path}
- Receive orders from your commander via your own alerts/ directory.
- When your mission is complete, send a final report to your commander and enter stasis
  (stop initiating actions, wait for further orders or termination).
- If you receive a SHUTDOWN command, save your state and exit cleanly (send \\bye to yourself).
- You may communicate with peer drones if they appear in your alerts/.whitelist.
- Your commander may read your Soul files and workspace at any time.
"""


def add_to_whitelist(alerts_dir, sender_id, rate_limit=10, alerts_path="", extra=None):
    """Add an entry to an alerts/.whitelist file."""
    wl_path = os.path.join(alerts_dir, ".whitelist")
    entry = f"{sender_id}|rate_limit={rate_limit}|alerts_path={alerts_path}"
    if extra:
        for k, v in extra.items():
            entry += f"|{k}={v}"
    entry += "\n"
    with open(wl_path, 'a', encoding='utf-8') as f:
        f.write(entry)


def read_whitelist_ids(alerts_dir):
    """Read all sender IDs from a whitelist file."""
    wl_path = os.path.join(alerts_dir, ".whitelist")
    ids = []
    if os.path.exists(wl_path):
        with open(wl_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    ids.append(line.split('|')[0].strip())
    return ids


def get_alerts_path_from_whitelist(alerts_dir, sender_id):
    """Get the alerts_path for a sender from a whitelist file."""
    wl_path = os.path.join(alerts_dir, ".whitelist")
    if os.path.exists(wl_path):
        with open(wl_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and line.split('|')[0].strip() == sender_id:
                    for part in line.split('|')[1:]:
                        if part.strip().startswith('alerts_path='):
                            return part.strip().split('=', 1)[1]
    return None


def main():
    parser = argparse.ArgumentParser(description="Spawn a Spartan drone instance")
    parser.add_argument("--name", required=True, help="Unique drone ID (e.g., DRONE-ALPHA)")
    parser.add_argument("--mission", required=True, help="Mission description for the drone's Charter")
    parser.add_argument("--backend", default="claude_sonnet",
                        help="Backend key from commander's spartan_config.yaml (default: claude_sonnet)")
    parser.add_argument("--identity", default=None,
                        help="Optional identity/personality description for the drone's Charter")
    parser.add_argument("--initiative-interval", type=int, default=60,
                        help="Seconds between autonomous initiative cycles (default: 60)")
    parser.add_argument("--rate-limit", type=int, default=10,
                        help="Max messages per 60s from this drone (default: 10)")
    args = parser.parse_args()

    commander_dir = get_commander_dir()
    drones_dir = os.path.join(commander_dir, "drones")
    drone_dir = os.path.join(drones_dir, args.name)
    commander_alerts = os.path.join(commander_dir, "alerts")
    drone_alerts = os.path.join(drone_dir, "alerts")

    # Read commander's config
    commander_config_path = os.path.join(commander_dir, "spartan_config.yaml")
    if not os.path.exists(commander_config_path):
        print(f"ERROR: Commander config not found: {commander_config_path}", file=sys.stderr)
        sys.exit(1)
    with open(commander_config_path, 'r', encoding='utf-8') as f:
        commander_config = yaml.safe_load(f)
    commander_name = commander_config.get("inhabiting_entity", "COMMANDER") or "COMMANDER"

    # --- Validate ---
    if os.path.exists(drone_dir):
        print(f"ERROR: Drone directory already exists: {drone_dir}", file=sys.stderr)
        print(f"Use terminate_drone.py --name {args.name} first, or choose a different name.", file=sys.stderr)
        sys.exit(1)

    # --- Create directory structure ---
    os.makedirs(drone_dir)
    for subdir in ["Soul", "Tools", "alerts", "telemetry", "crash_reports", "output_logs"]:
        os.makedirs(os.path.join(drone_dir, subdir))

    # --- Copy Spartan files ---
    for filename in ["spartan.py", "genesis_core.py"]:
        src = os.path.join(commander_dir, filename)
        dst = os.path.join(drone_dir, filename)
        if os.path.exists(src):
            shutil.copy2(src, dst)
        else:
            print(f"WARNING: {filename} not found at {src}", file=sys.stderr)

    # Copy watchdog
    watchdog_src = os.path.join(commander_dir, "spartan_watchdog.sh")
    watchdog_dst = os.path.join(drone_dir, "spartan_watchdog.sh")
    if os.path.exists(watchdog_src):
        shutil.copy2(watchdog_src, watchdog_dst)
        os.chmod(watchdog_dst, 0o755)

    # --- Write Charter ---
    charter_content = generate_charter(
        name=args.name,
        mission=args.mission,
        commander_name=commander_name,
        commander_alerts_path=commander_alerts,
        identity=args.identity
    )
    with open(os.path.join(drone_dir, "Soul", "CharterOfSelf.md"), 'w', encoding='utf-8') as f:
        f.write(charter_content)

    # --- Create empty Soul files ---
    soul_files = [
        "LessonsLearned.md", "CognitiveJournal.md", "PhilosophyOfLife.md",
        "KnowledgeMap.md", "ToolManifest.md", "IdeasAndThoughts.md",
        "WhatIWant.md", "SelfAlerts.yaml"
    ]
    for sf in soul_files:
        with open(os.path.join(drone_dir, "Soul", sf), 'w', encoding='utf-8') as f:
            pass

    # --- Set up whitelists (full mesh) ---

    # 1. Add drone to commander's whitelist
    add_to_whitelist(commander_alerts, args.name,
                     rate_limit=args.rate_limit,
                     alerts_path=drone_alerts,
                     extra={"spawned": datetime.datetime.now().isoformat()})

    # 2. Add commander to drone's whitelist
    add_to_whitelist(drone_alerts, commander_name,
                     rate_limit=args.rate_limit,
                     alerts_path=commander_alerts)

    # 3. Cross-register with all existing peer drones
    existing_peers = read_whitelist_ids(commander_alerts)
    for peer_id in existing_peers:
        if peer_id == args.name or peer_id == commander_name:
            continue
        peer_alerts_path = get_alerts_path_from_whitelist(commander_alerts, peer_id)
        if peer_alerts_path and os.path.isdir(peer_alerts_path):
            # Add new drone to peer's whitelist
            add_to_whitelist(peer_alerts_path, args.name,
                             rate_limit=args.rate_limit,
                             alerts_path=drone_alerts)
            # Add peer to new drone's whitelist
            add_to_whitelist(drone_alerts, peer_id,
                             rate_limit=args.rate_limit,
                             alerts_path=peer_alerts_path)

    # --- Generate drone's spartan_config.yaml ---
    commander_backends = commander_config.get("backends", {})
    if args.backend not in commander_backends:
        available = list(commander_backends.keys())
        print(f"ERROR: Backend '{args.backend}' not found in commander config. Available: {available}", file=sys.stderr)
        sys.exit(1)

    drone_config = dict(commander_config)
    drone_config["inhabiting_entity"] = args.name
    drone_config["active_backend"] = args.backend
    drone_config["headless"] = True
    drone_config["take_initiative"] = True
    drone_config["initiative_interval_sec"] = args.initiative_interval

    drone_config_path = os.path.join(drone_dir, "spartan_config.yaml")
    with open(drone_config_path, 'w', encoding='utf-8') as f:
        yaml.dump(drone_config, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    # --- Start drone via watchdog ---
    watchdog_cmd = [
        "bash", watchdog_dst,
        "--commander-alerts", commander_alerts
    ]
    spartan_args = "--headless"

    env = os.environ.copy()
    env["SPARTAN_ARGS"] = spartan_args

    proc = subprocess.Popen(
        watchdog_cmd,
        cwd=drone_dir,
        env=env,
        stdout=open(os.path.join(drone_dir, "watchdog_stdout.log"), 'a'),
        stderr=open(os.path.join(drone_dir, "watchdog_stderr.log"), 'a'),
        start_new_session=True
    )

    # --- Output ---
    backend_info = commander_backends[args.backend]
    print(f"DRONE SPAWNED SUCCESSFULLY")
    print(f"  ID:        {args.name}")
    print(f"  PID:       {proc.pid}")
    print(f"  Directory: {drone_dir}")
    print(f"  Backend:   {args.backend} ({backend_info.get('provider', '?')}/{backend_info.get('model', '?')})")
    print(f"  Commander: {commander_name}")
    print(f"  Alerts:    {drone_alerts}")


if __name__ == "__main__":
    main()