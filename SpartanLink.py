#!/usr/bin/env python3
"""
SpartanLink.py -- Collaborator Command Center
Communicate with all Spartan agents. View their updates. Monitor the family.

Place this file in SpartanHQ/ alongside spartan_link.yaml.
Subdirectories created automatically:
    SpartanHQ/
      SpartanLink.py
      spartan_link.yaml    -- configuration
      attachments/         -- pulled attachments from agents
      updates/             -- NAME_updates.json per agent
      comms_acc/           -- messages.json (persistent message history)

Usage:
    python SpartanLink.py
"""

import os
import sys
import subprocess
import datetime
import threading
import time
import json
import yaml
import pty
import select

import tkinter as tk
from tkinter import scrolledtext, font as tkfont

# ============================================================
# CONFIG LOADING
# ============================================================

APP_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(APP_DIR, "spartan_link.yaml")
ATTACHMENTS_DIR = os.path.join(APP_DIR, "attachments")
UPDATES_DIR = os.path.join(APP_DIR, "updates")
COMMS_DIR = os.path.join(APP_DIR, "comms_acc")
MESSAGES_FILE = os.path.join(COMMS_DIR, "messages.json")


def load_config():
    if not os.path.exists(CONFIG_FILE):
        print(f"FATAL: {CONFIG_FILE} not found.", file=sys.stderr)
        sys.exit(1)
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        cfg = yaml.safe_load(f)
    if not cfg:
        print(f"FATAL: {CONFIG_FILE} is empty or invalid.", file=sys.stderr)
        sys.exit(1)
    return cfg


def _ensure_dirs():
    for d in [ATTACHMENTS_DIR, UPDATES_DIR, COMMS_DIR]:
        os.makedirs(d, exist_ok=True)


def _resolve_spartan_link_dir(agent_cfg):
    return os.path.join(agent_cfg["spartan_path"], "spartan_link")


def _resolve_alerts_dir(agent_cfg):
    return os.path.join(agent_cfg["spartan_path"], "alerts")


# ============================================================
# PERSISTENCE
# ============================================================

def _load_messages():
    if os.path.exists(MESSAGES_FILE):
        try:
            with open(MESSAGES_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return []


def _save_messages(messages):
    try:
        with open(MESSAGES_FILE, 'w', encoding='utf-8') as f:
            json.dump(messages, f, indent=2)
    except Exception:
        pass


def _append_update(agent_name, update_data):
    fpath = os.path.join(UPDATES_DIR, f"{agent_name}_updates.json")
    existing = []
    if os.path.exists(fpath):
        try:
            with open(fpath, 'r', encoding='utf-8') as f:
                existing = json.load(f)
        except Exception:
            existing = []
    existing.append(update_data)
    with open(fpath, 'w', encoding='utf-8') as f:
        json.dump(existing, f, indent=2)


def _load_updates(agent_name):
    fpath = os.path.join(UPDATES_DIR, f"{agent_name}_updates.json")
    if os.path.exists(fpath):
        try:
            with open(fpath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return []


# ============================================================
# TRANSPORT
# ============================================================

def _ts():
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def _ts_display():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _run_ssh_cmd(cmd, password=None, timeout=30):
    """Run ssh/scp command. Uses pty to feed password if provided, otherwise plain subprocess."""
    if not password:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    pid, fd = pty.fork()
    if pid == 0:
        os.execvp(cmd[0], cmd)
    output = ""
    password_sent = False
    deadline = time.time() + timeout
    try:
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                os.kill(pid, 9)
                os.waitpid(pid, 0)
                return subprocess.CompletedProcess(cmd, 1, stdout=output, stderr="Timed out")
            r, _, _ = select.select([fd], [], [], min(remaining, 1.0))
            if not r:
                pid_result = os.waitpid(pid, os.WNOHANG)
                if pid_result[0] != 0:
                    return subprocess.CompletedProcess(cmd, os.WEXITSTATUS(pid_result[1]), stdout=output, stderr="")
                continue
            try:
                data = os.read(fd, 4096).decode(errors="replace")
            except OSError:
                break
            if not data:
                break
            output += data
            if not password_sent and "password" in output.lower():
                time.sleep(0.1)
                os.write(fd, (password + "\n").encode())
                password_sent = True
    except Exception:
        pass
    try:
        _, status = os.waitpid(pid, 0)
        return subprocess.CompletedProcess(cmd, os.WEXITSTATUS(status), stdout=output, stderr="")
    except ChildProcessError:
        return subprocess.CompletedProcess(cmd, 1, stdout=output, stderr="")
    finally:
        try:
            os.close(fd)
        except OSError:
            pass


def send_alert_local(alerts_path, sender_name, message):
    os.makedirs(alerts_path, exist_ok=True)
    filename = f"{sender_name}_{_ts()}.alert"
    filepath = os.path.join(alerts_path, filename)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(message)
    return filepath, None


def send_alert_scp(user, host, remote_alerts_path, sender_name, message, password=None):
    filename = f"{sender_name}_{_ts()}.alert"
    tmp_path = os.path.join("/tmp", f"spartanlink_tmp_{_ts()}.alert")
    try:
        with open(tmp_path, 'w', encoding='utf-8') as f:
            f.write(message)
        remote_dest = f"{user}@{host}:{remote_alerts_path}/{filename}"
        result = _run_ssh_cmd(
            ["scp", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=10",
             tmp_path, remote_dest],
            password=password, timeout=30
        )
        if result.returncode != 0:
            err_detail = (result.stderr or "").strip() or (result.stdout or "").strip() or f"exit code {result.returncode}"
            return None, f"SCP failed: {err_detail}"
        return remote_dest, None
    except subprocess.TimeoutExpired:
        return None, "SCP timed out"
    except Exception as e:
        return None, str(e)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def send_to_agent(agent_name, agent_cfg, sender_name, message):
    atype = agent_cfg.get("type", "")
    if atype == "local":
        alerts_path = _resolve_alerts_dir(agent_cfg)
        path, err = send_alert_local(alerts_path, sender_name, message)
        if err:
            return False, err
        return True, f"Local: {path}"
    elif atype == "remote":
        user = agent_cfg.get("user", "root")
        host = agent_cfg.get("host", "")
        password = agent_cfg.get("password")
        alerts_path = _resolve_alerts_dir(agent_cfg)
        dest, err = send_alert_scp(user, host, alerts_path, sender_name, message, password=password)
        if err:
            return False, err
        return True, f"Remote: {dest}"
    else:
        return False, f"Unknown agent type: {atype}"


def pull_from_agent_local(spartan_link_dir):
    messages, updates, attachments = [], [], []
    if not os.path.isdir(spartan_link_dir):
        return messages, updates, attachments
    for fname in sorted(os.listdir(spartan_link_dir)):
        fpath = os.path.join(spartan_link_dir, fname)
        if not os.path.isfile(fpath):
            continue
        try:
            if fname.endswith(".msg"):
                with open(fpath, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                os.remove(fpath)
                if content:
                    messages.append({"filename": fname, "content": content})
            elif fname.endswith(".update"):
                with open(fpath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                os.remove(fpath)
                updates.append(data)
            elif "_attach_" in fname:
                import shutil
                dest = os.path.join(ATTACHMENTS_DIR, fname)
                shutil.move(fpath, dest)
                attachments.append({"filename": fname, "local_path": dest})
        except Exception:
            try:
                os.remove(fpath)
            except OSError:
                pass
    return messages, updates, attachments


def pull_from_agent_remote(user, host, remote_spartan_link_dir, password=None):
    messages, updates, attachments = [], [], []
    try:
        ls_result = _run_ssh_cmd(
            ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=10",
             f"{user}@{host}", f"ls {remote_spartan_link_dir}/ 2>/dev/null"],
            password=password, timeout=15
        )
        if ls_result.returncode != 0 or not ls_result.stdout.strip():
            return messages, updates, attachments

        for fname in ls_result.stdout.strip().splitlines():
            fname = fname.strip()
            if not fname:
                continue
            remote_path = f"{remote_spartan_link_dir}/{fname}"
            local_tmp = f"/tmp/spartanlink_pull_{fname}"
            try:
                scp_result = _run_ssh_cmd(
                    ["scp", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=10",
                     f"{user}@{host}:{remote_path}", local_tmp],
                    password=password, timeout=30
                )
                if scp_result.returncode != 0 or not os.path.exists(local_tmp):
                    continue

                _run_ssh_cmd(
                    ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=10",
                     f"{user}@{host}", f"rm -f {remote_path}"],
                    password=password, timeout=10
                )

                if fname.endswith(".msg"):
                    with open(local_tmp, 'r', encoding='utf-8') as f:
                        content = f.read().strip()
                    os.remove(local_tmp)
                    if content:
                        messages.append({"filename": fname, "content": content})
                elif fname.endswith(".update"):
                    with open(local_tmp, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    os.remove(local_tmp)
                    updates.append(data)
                elif "_attach_" in fname:
                    import shutil
                    dest = os.path.join(ATTACHMENTS_DIR, fname)
                    shutil.move(local_tmp, dest)
                    attachments.append({"filename": fname, "local_path": dest})
                else:
                    os.remove(local_tmp)
            except Exception:
                if os.path.exists(local_tmp):
                    os.remove(local_tmp)
    except Exception:
        pass
    return messages, updates, attachments


# ============================================================
# GUI
# ============================================================

class SpartanLinkGUI:
    def __init__(self):
        _ensure_dirs()
        cfg = load_config()
        self.sender_name = cfg.get("sender_name", "Gene")
        self.agents = cfg.get("agents", {})
        self.poll_interval = cfg.get("poll_interval_sec", 30)

        self.root = tk.Tk()
        self.root.title("SpartanLink -- Command Center")
        self.root.geometry("1200x700")
        self.root.configure(bg="#1a1a2e")
        self.running = True
        self.selected_agent = None
        self.agent_buttons = {}
        self.message_history = _load_messages()
        self._build()
        self._load_message_history_to_display()
        self._start_poller()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build(self):
        mono = tkfont.Font(family="Menlo", size=11) if sys.platform == "darwin" else tkfont.Font(family="Consolas", size=10)
        mono_small = tkfont.Font(family="Menlo", size=10) if sys.platform == "darwin" else tkfont.Font(family="Consolas", size=9)
        self.mono = mono

        # --- Left Panel: Updates ---
        left_frame = tk.Frame(self.root, bg="#0a0a1a", width=350)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, padx=(5, 0), pady=5)
        left_frame.pack_propagate(False)

        tk.Label(left_frame, text="UPDATES", font=mono, bg="#0a0a1a", fg="#4a9eff").pack(pady=(5, 2))

        btn_frame = tk.Frame(left_frame, bg="#0a0a1a")
        btn_frame.pack(fill=tk.X, padx=5)
        for name in self.agents:
            btn = tk.Button(btn_frame, text=name, font=mono_small, width=12,
                            bg="#16213e", fg="#4a9eff", activebackground="#3a3a5c",
                            activeforeground="#ffffff",
                            command=lambda n=name: self._select_agent(n))
            btn.pack(side=tk.LEFT, padx=2, pady=2)
            self.agent_buttons[name] = btn

        self.updates_display = scrolledtext.ScrolledText(
            left_frame, wrap=tk.WORD, font=mono_small, bg="#0f0f23", fg="#cccccc",
            insertbackground="#ffffff", state=tk.DISABLED
        )
        self.updates_display.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # --- Right Panel: Messages ---
        right_frame = tk.Frame(self.root, bg="#1a1a2e")
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=5, pady=5)

        top_bar = tk.Frame(right_frame, bg="#1a1a2e")
        top_bar.pack(fill=tk.X, pady=(0, 2))

        tk.Label(top_bar, text="MESSAGES", font=mono, bg="#1a1a2e", fg="#4a9eff").pack(side=tk.LEFT)

        gather_btn = tk.Button(top_bar, text="Gather", font=mono_small,
                               bg="#16213e", fg="#50fa7b", activebackground="#3a3a5c",
                               activeforeground="#ffffff",
                               command=self._gather_now)
        gather_btn.pack(side=tk.RIGHT, padx=5)

        tk.Label(top_bar, text="sec", font=mono_small, bg="#1a1a2e", fg="#888888").pack(side=tk.RIGHT)
        self.poll_var = tk.StringVar(value=str(self.poll_interval))
        poll_entry = tk.Entry(top_bar, textvariable=self.poll_var, width=4,
                              bg="#16213e", fg="#ffffff", font=mono_small,
                              insertbackground="#ffffff")
        poll_entry.pack(side=tk.RIGHT, padx=2)
        poll_entry.bind("<Return>", self._update_poll_interval)
        tk.Label(top_bar, text="Poll:", font=mono_small, bg="#1a1a2e", fg="#888888").pack(side=tk.RIGHT)

        self.message_display = scrolledtext.ScrolledText(
            right_frame, wrap=tk.WORD, font=mono, bg="#0f0f23", fg="#cccccc",
            insertbackground="#ffffff", state=tk.DISABLED
        )
        self.message_display.pack(fill=tk.BOTH, expand=True)
        self.message_display.tag_configure("sent", foreground="#50fa7b")
        self.message_display.tag_configure("received", foreground="#8be9fd")
        self.message_display.tag_configure("update", foreground="#ffb86c")
        self.message_display.tag_configure("error", foreground="#ff5555")
        self.message_display.tag_configure("system", foreground="#6272a4")
        self.message_display.tag_configure("attachment", foreground="#bd93f9")

        # --- Input Bar ---
        input_frame = tk.Frame(right_frame, bg="#16213e")
        input_frame.pack(fill=tk.X, pady=(5, 0))

        recipient_frame = tk.Frame(input_frame, bg="#16213e")
        recipient_frame.pack(fill=tk.X, padx=5, pady=(5, 0))

        tk.Label(recipient_frame, text="To:", font=mono_small, bg="#16213e", fg="#888888").pack(side=tk.LEFT)
        self.recipient_vars = {}
        for name in self.agents:
            var = tk.BooleanVar(value=True)
            cb = tk.Checkbutton(recipient_frame, text=name, variable=var,
                                bg="#16213e", fg="#4a9eff", selectcolor="#0a0a1a",
                                activebackground="#16213e", activeforeground="#4a9eff",
                                font=mono_small)
            cb.pack(side=tk.LEFT, padx=5)
            self.recipient_vars[name] = var

        text_frame = tk.Frame(input_frame, bg="#16213e")
        text_frame.pack(fill=tk.X, padx=5, pady=5)

        self.input_text = tk.Text(text_frame, height=3, font=mono, bg="#1a1a2e", fg="#ffffff",
                                  insertbackground="#ffffff", wrap=tk.WORD)
        self.input_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.input_text.bind("<Return>", self._on_enter)
        self.input_text.bind("<Shift-Return>", lambda e: None)

        send_btn = tk.Button(text_frame, text="Send", command=self._send, font=mono, width=8,
                             bg="#16213e", fg="#50fa7b", activebackground="#3a3a5c",
                             activeforeground="#ffffff")
        send_btn.pack(side=tk.RIGHT, padx=(5, 0))

    def _on_enter(self, event):
        if not event.state & 0x1:
            self._send()
            return "break"

    def _update_poll_interval(self, event=None):
        try:
            val = int(self.poll_var.get())
            self.poll_interval = max(5, val)
            self.poll_var.set(str(self.poll_interval))
        except ValueError:
            pass

    def _send(self):
        text = self.input_text.get("1.0", tk.END).strip()
        if not text:
            return
        self.input_text.delete("1.0", tk.END)

        targets = [name for name, var in self.recipient_vars.items() if var.get()]
        if not targets:
            self._append_message("[No recipients selected]", "error")
            return

        sr_tag = "\n[Sent VIA Spartan Radio, if replying, please also use Spartan Radio.]"
        #sr_tag = ""
        if len(targets) > 1:
            cc_line = f"\n[CC: {', '.join(targets)}]"
            text_with_cc = text + sr_tag + cc_line
        else:
            text_with_cc = text + sr_tag
        for name in targets:
            cfg = self.agents[name]
            ok, detail = send_to_agent(name, cfg, self.sender_name, text_with_cc)
            ts = _ts_display()
            if ok:
                msg_text = f"[{ts}] {self.sender_name} -> {name}: {text}"
                self._append_message(msg_text, "sent")
                self._persist_message({"ts": ts, "direction": "sent", "from": self.sender_name, "to": name, "text": text})
            else:
                self._append_message(f"[{ts}] FAILED -> {name}: {detail}", "error")

    def _append_message(self, text, tag="received"):
        self.message_display.configure(state=tk.NORMAL)
        self.message_display.insert(tk.END, text + "\n", tag)
        self.message_display.see(tk.END)
        self.message_display.configure(state=tk.DISABLED)

    def _persist_message(self, msg_data):
        self.message_history.append(msg_data)
        _save_messages(self.message_history)

    def _load_message_history_to_display(self):
        for msg in self.message_history:
            direction = msg.get("direction", "received")
            ts = msg.get("ts", "??:??:??")
            if direction == "sent":
                text = f"[{ts}] {msg.get('from', 'Gene')} -> {msg.get('to', '?')}: {msg.get('text', '')}"
                tag = "sent"
            else:
                sender = msg.get("from", "?")
                target = msg.get("to", "Gene")
                text = f"[{ts}] {sender} -> {target}: {msg.get('text', '')}"
                tag = "received"
            self._append_message(text, tag)

    def _select_agent(self, agent_name):
        self.selected_agent = agent_name
        for name, btn in self.agent_buttons.items():
            if name == agent_name:
                btn.configure(bg="#3a3a5c", fg="#ffffff")
            else:
                btn.configure(bg="#16213e", fg="#4a9eff")
        self._refresh_updates()

    def _refresh_updates(self):
        if not self.selected_agent:
            return
        updates = _load_updates(self.selected_agent)
        self.updates_display.configure(state=tk.NORMAL)
        self.updates_display.delete("1.0", tk.END)
        if not updates:
            self.updates_display.insert(tk.END, f"[No updates from {self.selected_agent}]")
        else:
            for u in updates:
                ts = u.get("timestamp", "?")
                title = u.get("title", "Untitled")
                body = u.get("body", "")
                self.updates_display.insert(tk.END, f"[{ts}] {title}\n{body}\n\n")
        self.updates_display.see(tk.END)
        self.updates_display.configure(state=tk.DISABLED)

    def _gather_now(self):
        threading.Thread(target=self._do_gather, daemon=True).start()

    def _do_gather(self):
        self._poll_all()
        if self.selected_agent:
            try:
                self.root.after(0, self._refresh_updates)
            except Exception:
                pass

    def _start_poller(self):
        def poll_loop():
            while self.running:
                time.sleep(self.poll_interval)
                if not self.running:
                    break
                self._poll_all()
                if self.selected_agent:
                    try:
                        self.root.after(0, self._refresh_updates)
                    except Exception:
                        pass
        t = threading.Thread(target=poll_loop, daemon=True)
        t.start()

    def _poll_all(self):
        for name, cfg in self.agents.items():
            try:
                atype = cfg.get("type", "")
                if atype == "local":
                    sl_dir = _resolve_spartan_link_dir(cfg)
                    msgs, updates, attachments = pull_from_agent_local(sl_dir)
                elif atype == "remote":
                    user = cfg.get("user", "root")
                    host = cfg.get("host", "")
                    password = cfg.get("password")
                    sl_dir = _resolve_spartan_link_dir(cfg)
                    msgs, updates, attachments = pull_from_agent_remote(user, host, sl_dir, password=password)
                else:
                    continue

                for msg in msgs:
                    ts = _ts_display()
                    fname = msg["filename"]
                    content = msg["content"]
                    parts = fname.replace(".msg", "").split("_to_", 1)
                    if len(parts) == 2:
                        sender = parts[0]
                        target_part = parts[1].rsplit("_", 2)[0]
                        display = f"[{ts}] {sender} -> {target_part}: {content}"
                        msg_data = {"ts": ts, "direction": "received", "from": sender, "to": target_part, "text": content}
                    else:
                        display = f"[{ts}] {name}: {content}"
                        msg_data = {"ts": ts, "direction": "received", "from": name, "to": "Gene", "text": content}
                    self._persist_message(msg_data)
                    try:
                        self.root.after(0, lambda d=display: self._append_message(d, "received"))
                    except Exception:
                        pass

                for update in updates:
                    agent_from = update.get("from", name)
                    _append_update(agent_from, update)
                    ts = _ts_display()
                    title = update.get("title", "Untitled")
                    display = f"[{ts}] UPDATE from {agent_from}: {title}"
                    try:
                        self.root.after(0, lambda d=display: self._append_message(d, "update"))
                    except Exception:
                        pass

                for att in attachments:
                    ts = _ts_display()
                    display = f"[{ts}] ATTACHMENT from {name}: {att['filename']} -> {att['local_path']}"
                    try:
                        self.root.after(0, lambda d=display: self._append_message(d, "attachment"))
                    except Exception:
                        pass

            except Exception:
                pass

    def _on_close(self):
        self.running = False
        _save_messages(self.message_history)
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    SpartanLinkGUI().run()
