#!/usr/bin/env python3
"""
SpartanRadio.py -- Inter-agent and agent-to-Gene communication tool.
Drop this in your Tools/ directory. Edit the CONFIGURATION section below.

**Note on SpartanRadio Configuration:**
SpartanRadio ships with a default contact type of `"gene"` for the human collaborator. This is a routing identifier, not a fixed requirement. To use your own collaborator name, update the contact type in `Tools/SpartanRadio.py` and the corresponding references in the entity's genesis_core documentation. Messages to the collaborator contact type are routed to the `spartan_link/` directory rather than to an `alerts/` directory.

=== DOCUMENTATION ===

PURPOSE:
    Send messages, updates, and files to Gene or other Spartan agents.
    File-based messaging. Local targets get direct file writes.
    Remote targets get SCP delivery. Gene never runs a server -- he
    pulls your messages from your spartan_link/ directory via SpartanLink.

SETUP:
    1. Set MY_NAME to your name.
    2. Add contacts to the CONTACTS dict. Three contact types:

       "Gene":     type "gene". Messages and updates go to your local
                   spartan_link/ directory. Gene pulls them with SpartanLink.

       Local agent: type "local". Direct file write to their alerts/ directory.
                   Same machine, no SSH needed.
                   Required field: alerts_path (full path to their alerts/ dir)

       Remote agent: type "remote". SCP to their alerts/ directory on another
                   machine. Required fields: user, host, alerts_path
                   Prerequisite: SSH key access to the target machine.

USAGE (via execute_console):

    Send message to Gene:
        python Tools/SpartanRadio.py --target Gene --message "Overnight run complete."

    Send message to a peer agent (CC to Gene by default):
        python Tools/SpartanRadio.py --target Virgil --message "Need your analysis."

    Send without CC:
        python Tools/SpartanRadio.py --target Virgil --message "Private note." --no-cc

    Broadcast to all contacts:
        python Tools/SpartanRadio.py --broadcast --message "Migration complete."

    Send a status update to Gene:
        python Tools/SpartanRadio.py --update --title "Calibration Complete" --body "Finished limbic system. Zero errors."

    Send message with file attachment:
        python Tools/SpartanRadio.py --target Virgil --message "Here is the data." --attach /path/to/data.csv

    Send attachment to Gene:
        python Tools/SpartanRadio.py --target Gene --message "Report attached." --attach /path/to/report.pdf

CC BEHAVIOR:
    By default, every message to another agent also writes a copy to your
    spartan_link/ directory so Gene can see it via SpartanLink. Use --no-cc
    to suppress. Messages to Gene never produce a CC (they already go to
    spartan_link/).

FILE FORMATS:
    Alert files delivered to agents: {MY_NAME}_{timestamp}.alert
    Gene-bound messages: {MY_NAME}_to_{TARGET}_{timestamp}.msg
    Gene-bound updates: {MY_NAME}_{timestamp}.update (JSON with title, body, timestamp)
    Attachments: {MY_NAME}_{timestamp}_attach_{original_filename}

DIRECTORIES:
    spartan_link/ sits INSIDE your Spartan directory (same level as alerts/).
    It is created automatically on first use.

HOW RECIPIENTS RECEIVE YOUR MESSAGES:
    Agents: FileWatcher picks up .alert files from their alerts/ dir.
    Your message appears in their STM as: [Message From: {MY_NAME}] message
    The sender must be in the receiving agent's alerts/.whitelist.
    Gene: SpartanLink app polls your spartan_link/ dir and pulls messages.

=== END DOCUMENTATION ===
"""

import os
import sys
import subprocess
import datetime
import argparse
import json

# ============================================================
# CONFIGURATION -- Edit this section for your agent
# ============================================================

MY_NAME = "NewEntity"

CONTACTS = {
    "Gene": {
        "type": "gene",
    },
    # "Entity_1": {
    #     "type": "local",
    #     "alerts_path": "/path/to/Spartan_Entity_1/alerts",
    # },
    # "Entity_2": {
    #     "type": "remote",
    #     "user": "your_ssh_user",
    #     "host": "192.168.x.x",
    #     "alerts_path": "/path/to/Spartan_Enitity_2/alerts",
    # },
}

# ============================================================
# IMPLEMENTATION
# ============================================================

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SPARTAN_DIR = os.path.dirname(SCRIPT_DIR)
SPARTANLINK_DIR = os.path.join(SPARTAN_DIR, "spartan_link")


def _ts():
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def _ts_display():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _ensure_dir(path):
    os.makedirs(path, exist_ok=True)


def _write_alert(alerts_path, message):
    """Write an alert file to a local alerts/ directory."""
    _ensure_dir(alerts_path)
    filename = f"{MY_NAME}_{_ts()}.alert"
    filepath = os.path.join(alerts_path, filename)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(message)
    return filepath


def _scp_file(user, host, local_path, remote_path):
    """SCP a local file to a remote path. Returns (success, error_string)."""
    try:
        result = subprocess.run(
            ["scp", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=10",
             local_path, f"{user}@{host}:{remote_path}"],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode != 0:
            return False, f"SCP failed (rc={result.returncode}): {result.stderr.strip()}"
        return True, None
    except subprocess.TimeoutExpired:
        return False, "SCP timed out after 60s"
    except Exception as e:
        return False, f"SCP error: {e}"


def _scp_alert(user, host, remote_alerts_path, message):
    """Write a temp alert file locally, SCP it to the remote machine, clean up."""
    ts = _ts()
    filename = f"{MY_NAME}_{ts}.alert"
    tmp_path = os.path.join(SPARTAN_DIR, f".radio_tmp_{ts}.alert")
    try:
        with open(tmp_path, 'w', encoding='utf-8') as f:
            f.write(message)
        ok, err = _scp_file(user, host, tmp_path, f"{remote_alerts_path}/{filename}")
        if not ok:
            return None, err
        return f"{user}@{host}:{remote_alerts_path}/{filename}", None
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def _write_to_spartan_link(target_name, message, suffix=".msg"):
    """Write a file to spartan_link/ for Gene to pick up."""
    _ensure_dir(SPARTANLINK_DIR)
    filename = f"{MY_NAME}_to_{target_name}_{_ts()}{suffix}"
    filepath = os.path.join(SPARTANLINK_DIR, filename)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(message)
    return filepath


def _handle_attachment_local(attach_path, target_alerts_path):
    """Copy an attachment to a local target's alerts/ dir."""
    if not os.path.exists(attach_path):
        return None, f"Attachment not found: {attach_path}"
    _ensure_dir(target_alerts_path)
    original_name = os.path.basename(attach_path)
    dest_name = f"{MY_NAME}_{_ts()}_attach_{original_name}"
    dest_path = os.path.join(target_alerts_path, dest_name)
    try:
        import shutil
        shutil.copy2(attach_path, dest_path)
        return dest_path, None
    except Exception as e:
        return None, f"Attachment copy failed: {e}"


def _handle_attachment_remote(attach_path, user, host, remote_alerts_path):
    """SCP an attachment to a remote target's alerts/ dir."""
    if not os.path.exists(attach_path):
        return None, f"Attachment not found: {attach_path}"
    original_name = os.path.basename(attach_path)
    dest_name = f"{MY_NAME}_{_ts()}_attach_{original_name}"
    ok, err = _scp_file(user, host, attach_path, f"{remote_alerts_path}/{dest_name}")
    if not ok:
        return None, err
    return f"{user}@{host}:{remote_alerts_path}/{dest_name}", None


def _handle_attachment_gene(attach_path):
    """Copy an attachment to spartan_link/ for Gene to pick up."""
    if not os.path.exists(attach_path):
        return None, f"Attachment not found: {attach_path}"
    _ensure_dir(SPARTANLINK_DIR)
    original_name = os.path.basename(attach_path)
    dest_name = f"{MY_NAME}_{_ts()}_attach_{original_name}"
    dest_path = os.path.join(SPARTANLINK_DIR, dest_name)
    try:
        import shutil
        shutil.copy2(attach_path, dest_path)
        return dest_path, None
    except Exception as e:
        return None, f"Attachment copy failed: {e}"


def send_message(target_name, message, cc_gene=True, attach_path=None):
    """Send a message to a target. Returns (success_bool, detail_string)."""
    if target_name == MY_NAME:
        return False, "Cannot send a message to yourself."

    if target_name not in CONTACTS:
        available = list(CONTACTS.keys())
        return False, f"Unknown target '{target_name}'. Available: {available}"

    contact = CONTACTS[target_name]
    ctype = contact.get("type", "")
    results = []

    if ctype == "gene":
        path = _write_to_spartan_link("Gene", message)
        results.append(f"Delivered to Gene via {path}")
        if attach_path:
            apath, aerr = _handle_attachment_gene(attach_path)
            if aerr:
                results.append(f"Attachment FAILED: {aerr}")
            else:
                results.append(f"Attachment: {apath}")

    elif ctype == "local":
        alerts_path = contact.get("alerts_path", "")
        if not alerts_path:
            return False, f"No alerts_path configured for {target_name}."
        path = _write_alert(alerts_path, message)
        results.append(f"Local delivery: {path}")
        if attach_path:
            apath, aerr = _handle_attachment_local(attach_path, alerts_path)
            if aerr:
                results.append(f"Attachment FAILED: {aerr}")
            else:
                results.append(f"Attachment: {apath}")

    elif ctype == "remote":
        user = contact.get("user", "")
        host = contact.get("host", "")
        alerts_path = contact.get("alerts_path", "")
        if not user or not host or not alerts_path:
            return False, f"Missing user, host, or alerts_path for {target_name}."
        dest, err = _scp_alert(user, host, alerts_path, message)
        if err:
            return False, err
        results.append(f"Remote delivery: {dest}")
        if attach_path:
            apath, aerr = _handle_attachment_remote(attach_path, user, host, alerts_path)
            if aerr:
                results.append(f"Attachment FAILED: {aerr}")
            else:
                results.append(f"Attachment: {apath}")

    else:
        return False, f"Unknown contact type '{ctype}' for {target_name}."

    if cc_gene and ctype != "gene":
        cc_path = _write_to_spartan_link(target_name, message)
        results.append(f"CC Gene: {cc_path}")

    return True, " | ".join(results)


def send_update(title, body):
    """Send a structured status update to Gene. Returns (success_bool, detail_string)."""
    _ensure_dir(SPARTANLINK_DIR)
    ts = _ts()
    update_data = {
        "type": "update",
        "from": MY_NAME,
        "timestamp": _ts_display(),
        "title": title,
        "body": body
    }
    filename = f"{MY_NAME}_{ts}.update"
    filepath = os.path.join(SPARTANLINK_DIR, filename)
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(update_data, f, indent=2)
    return True, f"Update sent: {filepath}"


def broadcast(message, cc_gene=True, attach_path=None):
    """Send to all contacts. Returns summary string."""
    lines = []
    for name in CONTACTS:
        ok, detail = send_message(name, message, cc_gene=cc_gene, attach_path=attach_path)
        status = "OK" if ok else "FAILED"
        lines.append(f"  {name}: [{status}] {detail}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="SpartanRadio -- Inter-agent communication")
    parser.add_argument("--target", "-t", type=str, help="Target contact name")
    parser.add_argument("--message", "-m", type=str, help="Message text")
    parser.add_argument("--broadcast", "-b", action="store_true", help="Send to all contacts")
    parser.add_argument("--no-cc", action="store_true", help="Do not CC Gene")
    parser.add_argument("--attach", "-a", type=str, help="Path to file attachment")
    parser.add_argument("--update", "-u", action="store_true", help="Send a status update to Gene")
    parser.add_argument("--title", type=str, help="Update title (required with --update)")
    parser.add_argument("--body", type=str, help="Update body (required with --update)")
    args = parser.parse_args()

    cc = not args.no_cc

    if args.update:
        if not args.title or not args.body:
            print("Error: --update requires --title and --body", file=sys.stderr)
            sys.exit(1)
        ok, detail = send_update(args.title, args.body)
        if ok:
            print(f"[SpartanRadio] {detail}")
        else:
            print(f"[SpartanRadio] FAILED: {detail}", file=sys.stderr)
            sys.exit(1)
    elif args.broadcast:
        if not args.message:
            print("Error: --broadcast requires --message", file=sys.stderr)
            sys.exit(1)
        print(f"[SpartanRadio] Broadcasting from {MY_NAME}:")
        print(broadcast(args.message, cc_gene=cc, attach_path=args.attach))
    elif args.target:
        if not args.message:
            print("Error: --target requires --message", file=sys.stderr)
            sys.exit(1)
        ok, detail = send_message(args.target, args.message, cc_gene=cc, attach_path=args.attach)
        if ok:
            print(f"[SpartanRadio] {detail}")
        else:
            print(f"[SpartanRadio] FAILED: {detail}", file=sys.stderr)
            sys.exit(1)
    else:
        print("Error: specify --target NAME, --broadcast, or --update", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
