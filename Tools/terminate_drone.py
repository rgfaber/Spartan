#!/usr/bin/env python3
"""
terminate_drone.py — Cleanly terminates a Spartan drone instance.

Usage:
    python Tools/terminate_drone.py --name DRONE-ALPHA [--archive] [--delete]

--archive: Move drone directory to drones/_archive/DRONE-ALPHA_TIMESTAMP/
--delete:  Permanently delete drone directory (WARNING: destroys Soul and memories)
Neither:   Drone directory is left in place (stasis — can be restarted later)
"""

import argparse
import os
import sys
import signal
import time
import shutil
import datetime
import yaml


def get_commander_dir():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def remove_from_whitelist(alerts_dir, sender_id):
    """Remove a sender from an alerts/.whitelist file."""
    wl_path = os.path.join(alerts_dir, ".whitelist")
    if not os.path.exists(wl_path):
        return
    with open(wl_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    with open(wl_path, 'w', encoding='utf-8') as f:
        for line in lines:
            stripped = line.strip()
            if stripped and not stripped.startswith('#'):
                if stripped.split('|')[0].strip() != sender_id:
                    f.write(line)
            else:
                f.write(line)


def read_whitelist_entries(alerts_dir):
    """Read all whitelist entries as (sender_id, alerts_path) tuples."""
    wl_path = os.path.join(alerts_dir, ".whitelist")
    entries = []
    if os.path.exists(wl_path):
        with open(wl_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    parts = line.split('|')
                    sender_id = parts[0].strip()
                    alerts_path = ""
                    for part in parts[1:]:
                        if part.strip().startswith('alerts_path='):
                            alerts_path = part.strip().split('=', 1)[1]
                    entries.append((sender_id, alerts_path))
    return entries


def find_drone_pid(drone_dir):
    """Attempt to find the drone's process."""
    try:
        result = os.popen(f"pgrep -f 'spartan.py.*--headless' -a 2>/dev/null").read()
        for line in result.strip().split('\n'):
            if drone_dir in line or os.path.basename(drone_dir) in line:
                return int(line.split()[0])
    except Exception:
        pass
    try:
        result = os.popen(f"pgrep -f 'spartan_watchdog.sh' -a 2>/dev/null").read()
        for line in result.strip().split('\n'):
            if drone_dir in line or os.path.basename(drone_dir) in line:
                return int(line.split()[0])
    except Exception:
        pass
    return None


def main():
    parser = argparse.ArgumentParser(description="Terminate a Spartan drone instance")
    parser.add_argument("--name", required=True, help="Drone ID to terminate")
    parser.add_argument("--archive", action="store_true",
                        help="Archive drone directory instead of leaving in place")
    parser.add_argument("--delete", action="store_true",
                        help="Permanently delete drone directory (DESTROYS SOUL)")
    args = parser.parse_args()

    if args.archive and args.delete:
        print("ERROR: Cannot use both --archive and --delete", file=sys.stderr)
        sys.exit(1)

    commander_dir = get_commander_dir()
    drone_dir = os.path.join(commander_dir, "drones", args.name)
    drone_alerts = os.path.join(drone_dir, "alerts")
    commander_alerts = os.path.join(commander_dir, "alerts")

    if not os.path.exists(drone_dir):
        print(f"ERROR: Drone directory not found: {drone_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"Terminating drone: {args.name}")

    # --- 1. Send SHUTDOWN alert to drone ---
    try:
        commander_name = "COMMANDER"
        commander_config_path = os.path.join(commander_dir, "spartan_config.yaml")
        if os.path.exists(commander_config_path):
            with open(commander_config_path, 'r', encoding='utf-8') as f:
                cfg = yaml.safe_load(f)
            commander_name = cfg.get("inhabiting_entity", "COMMANDER") or "COMMANDER"

        shutdown_file = os.path.join(drone_alerts, f"{commander_name}_shutdown.alert")
        with open(shutdown_file, 'w', encoding='utf-8') as f:
            f.write(f"Shutdown requested by {commander_name}. SIGTERM will follow.\n")
        print(f"  SHUTDOWN alert sent.")
    except Exception as e:
        print(f"  WARNING: Could not send SHUTDOWN alert: {e}", file=sys.stderr)

    # --- 2. Wait briefly for clean shutdown ---
    print(f"  Waiting 10 seconds for clean shutdown...")
    time.sleep(10)

    # --- 3. Terminate process if still running ---
    pid = find_drone_pid(drone_dir)
    if pid:
        print(f"  Drone still running (PID {pid}). Sending SIGTERM...")
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
            time.sleep(3)
            try:
                os.kill(pid, 0)
                print(f"  Still alive. Sending SIGKILL...")
                os.killpg(os.getpgid(pid), signal.SIGKILL)
            except ProcessLookupError:
                print(f"  Process terminated cleanly.")
        except Exception as e:
            print(f"  WARNING: Could not kill process: {e}", file=sys.stderr)
    else:
        print(f"  No running process found.")

    # --- 4. Remove drone from all peer whitelists ---
    drone_peers = read_whitelist_entries(drone_alerts)
    for peer_id, peer_alerts_path in drone_peers:
        if peer_alerts_path and os.path.isdir(peer_alerts_path):
            remove_from_whitelist(peer_alerts_path, args.name)
            print(f"  Removed {args.name} from {peer_id}'s whitelist.")

    # Also remove from commander's whitelist
    remove_from_whitelist(commander_alerts, args.name)
    print(f"  Removed {args.name} from commander's whitelist.")

    # --- 5. Handle drone directory ---
    if args.archive:
        archive_dir = os.path.join(commander_dir, "drones", "_archive")
        os.makedirs(archive_dir, exist_ok=True)
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        archive_dest = os.path.join(archive_dir, f"{args.name}_{timestamp}")
        shutil.move(drone_dir, archive_dest)
        print(f"  Archived to: {archive_dest}")
    elif args.delete:
        shutil.rmtree(drone_dir)
        print(f"  DELETED: {drone_dir} (Soul and memories destroyed)")
    else:
        print(f"  Directory preserved at: {drone_dir} (can be restarted later)")

    print(f"DRONE {args.name} TERMINATED SUCCESSFULLY")


if __name__ == "__main__":
    main()