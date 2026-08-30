#!/usr/bin/env python3
"""serial_client.py - drives the Lumo OS live guest through the QEMU serial
console (TCP chardev). Logs in, runs diagnostics and collects screenshots
as base64 streams. Network-independent (works even without guest networking).
"""
import base64
import socket
import sys
import time

HOST, PORT = "127.0.0.1", 4555


class Serial:
    def __init__(self, port=PORT):
        self.sock = socket.create_connection((HOST, port), timeout=10)
        self.sock.settimeout(0.5)
        self.buf = b""
        self.raw_log = []

    def _reply_to_terminal_queries(self, chunk):
        # agetty/login probe the terminal with ESC[6n (cursor position);
        # a real terminal answers - emulate one so the guest never blocks.
        if b"\x1b[6n" in chunk:
            try:
                self.sock.sendall(b"\x1b[32766;32766R")
            except Exception:
                pass

    def read_avail(self, limit=65536):
        try:
            while True:
                chunk = self.sock.recv(65536)
                if not chunk:
                    break
                self._reply_to_terminal_queries(chunk)
                self.buf += chunk
                if len(self.raw_log) < 4000:
                    self.raw_log.append(chunk)
                if len(self.buf) > 8 * 1024 * 1024:
                    self.buf = self.buf[-4 * 1024 * 1024:]
        except socket.timeout:
            pass
        except Exception:
            pass

    def read_until(self, patterns, timeout):
        """Wait until any of the byte patterns appears in the buffer."""
        end = time.time() + timeout
        pats = [p.encode() if isinstance(p, str) else p for p in patterns]
        while time.time() < end:
            self.read_avail()
            for p in pats:
                idx = self.buf.find(p)
                if idx >= 0:
                    out = self.buf[: idx + len(p)]
                    self.buf = self.buf[idx + len(p):]
                    return out.decode(errors="replace")
            time.sleep(0.2)
        tail = self.buf[-3000:].decode(errors="replace")
        raise TimeoutError(f"serial timeout waiting for {patterns}; tail:\n{tail}")

    def send(self, text):
        if isinstance(text, str):
            text = text.replace("\n", "\r")
            text = text.encode()
        self.sock.sendall(text)

    def sendline(self, line=""):
        # CR is the correct terminal Enter; guest icrnl translates to LF
        self.send(line + "\r")

    def drain(self, seconds=1.0):
        end = time.time() + seconds
        while time.time() < end:
            self.read_avail()
            time.sleep(0.1)
        out = self.buf.decode(errors="replace")
        self.buf = b""
        return out


def run_command(ser, cmd, timeout=120, marker=None):
    """Run a command at the shell prompt, return its output (minus echo)."""
    marker = marker or f"CMDDONE{time.time_ns() % 100000}"
    ser.buf = b""
    ser.sendline(cmd + f"; echo {marker}")
    out = ser.read_until([marker], timeout)
    # strip the echoed command and the marker itself
    lines = out.splitlines()
    if lines and lines[0].rstrip().endswith(cmd.split(";")[0].strip()[-40:]):
        lines = lines[1:]
    result = "\n".join(lines[:-1])  # drop marker line
    return result


def main():
    shots_dir = sys.argv[1] if len(sys.argv) > 1 else "build/screenshots"
    os_mkdir = True

    print("[serial] waiting for login prompt (up to 12 min)...")
    ser = Serial()
    deadline_shots = time.time() + 45 * 60

    # login (retry - the user may not exist yet right after boot)
    logged_in = False
    for attempt in range(12):
        try:
            ser.read_until(["login:"], timeout=120)
        except TimeoutError:
            pass
        time.sleep(2)
        ser.sendline("lumo")
        try:
            echo = ser.read_until(["Password:", "incorrect", "$ ", "# "], timeout=30)
            if "incorrect" in echo:
                print(f"[serial] attempt {attempt}: login incorrect, retrying...")
                continue
            if "Password:" in echo:
                time.sleep(1)
                ser.sendline("lumo")
                echo2 = ser.read_until(["$ ", "# ", "incorrect", "Login"], timeout=30)
                if "incorrect" in echo2:
                    print(f"[serial] attempt {attempt}: bad password, retrying...")
                    continue
            logged_in = True
            break
        except TimeoutError:
            tail = b"".join(ser.raw_log[-12:]).decode(errors="replace")[-500:]
            print(f"[serial] attempt {attempt}: prompt never advanced; raw tail:\n{tail!r}")
            continue
    if not logged_in:
        print("[serial] FAIL: could not log in over serial")
        tail = b"".join(ser.raw_log[-40:]).decode(errors="replace")[-2500:]
        print(tail)
        sys.exit(1)
    print("[serial] logged in as lumo")
    time.sleep(1)
    ser.drain(1)

    # ---------------- diagnostics ----------------
    print("[serial] === diagnostics ===")
    for cmd in (
        "export PS1='PROMPT> '",
        "date",
        "ip -4 addr show 2>/dev/null | grep -E 'inet|^[0-9]'",
        "systemctl is-active NetworkManager ssh sddm",
        "systemctl --failed --no-legend --no-pager",
        "cat /run/lumo-test-mode 2>/dev/null && echo TEST_MODE_OK",
        "ls /run/user/$(id -u)/ 2>/dev/null",
    ):
        try:
            out = run_command(ser, cmd, timeout=60)
            print(f"$ {cmd}\n{out}\n")
        except TimeoutError as exc:
            print(f"$ {cmd} -> TIMEOUT\n{exc}\n")

    # ---------------- wait for the Wayland session ----------------
    print("[serial] waiting for the Wayland session socket...")
    run_command(
        ser,
        "for i in $(seq 1 120); do test -S /run/user/$(id -u)/wayland-0 && break; "
        "test -S /run/user/$(id -u)/wayland-1 && break; sleep 5; done",
        timeout=700,
    )
    socks = run_command(ser, "ls /run/user/$(id -u)/ | grep wayland", timeout=30)
    print(f"[serial] sockets: {socks.strip() or 'NONE'}")
    if "wayland" not in socks:
        print("[serial] FAIL: no wayland socket; session diagnostics:")
        print(run_command(ser,
            "systemctl status display-manager --no-pager -l 2>/dev/null | tail -n 30; "
            "journalctl -b --no-pager | grep -iE 'labwc|sddm|greeter|wayland' | tail -n 40",
            timeout=60))
        sys.exit(1)

    # ---------------- screenshots inside the guest ----------------
    print("[serial] transferring and running the screenshot script...")
    shot_script = r"""#!/bin/sh
export XDG_RUNTIME_DIR=/run/user/$(id -u)
export WAYLAND_DISPLAY=$(ls "$XDG_RUNTIME_DIR"/wayland-* 2>/dev/null | head -n1 | xargs -r basename)
export XDG_CURRENT_DESKTOP=lumo:wlroots
export HOME=/home/lumo
SHOTS=/tmp/lumo-shots
rm -rf "$SHOTS"; mkdir -p "$SHOTS"
grim "$SHOTS/00-desktop.png" 2>"$SHOTS/00.err" || true

lumo-launcher >/dev/null 2>&1 & sleep 3; grim "$SHOTS/01-launcher.png" 2>/dev/null; pkill -f lumo-launcher 2>/dev/null
lumo-qs >/dev/null 2>&1 & sleep 3; grim "$SHOTS/02-quick-settings.png" 2>/dev/null; pkill -f lumo-qs 2>/dev/null
lumo-calendar >/dev/null 2>&1 & sleep 2; grim "$SHOTS/03-calendar.png" 2>/dev/null; pkill -f lumo-calendar 2>/dev/null
lumo-power >/dev/null 2>&1 & sleep 2; grim "$SHOTS/04-power.png" 2>/dev/null; pkill -f lumo-power 2>/dev/null
lumo-store >/dev/null 2>&1 & sleep 7; grim "$SHOTS/05-store.png" 2>/dev/null; pkill -f lumo-store 2>/dev/null
lumo-settings >/dev/null 2>&1 & sleep 6; grim "$SHOTS/06-settings.png" 2>/dev/null; pkill -f lumo-settings 2>/dev/null
foot >/dev/null 2>&1 & sleep 3; grim "$SHOTS/07-terminal.png" 2>/dev/null; pkill -x foot 2>/dev/null

QT_QPA_PLATFORM=wayland sddm-greeter --test-mode --theme /usr/share/sddm/themes/lumo >/tmp/greeter.log 2>&1 &
sleep 5; grim "$SHOTS/08-greeter.png" 2>/dev/null; pkill -f sddm-greeter 2>/dev/null

cat > "$SHOTS/index.txt" <<IDX
$(ls -la "$SHOTS" | tail -n +2)
$(cat "$SHOTS/00.err" 2>/dev/null)
DONE_MARKER_XY
IDX
echo SHOTS_COMPLETE
"""
    # feed the script line by line via a heredoc
    ser.sendline("cat > /tmp/lumo-shots.sh << 'SHOTSEOF'")
    for line in shot_script.splitlines():
        ser.sendline(line)
        time.sleep(0.01)
    ser.sendline("SHOTSEOF")
    out = ser.read_until(["SHOTSEOF"], timeout=60)
    run_command(ser, "chmod +x /tmp/lumo-shots.sh", timeout=30)
    result = run_command(ser, "/tmp/lumo-shots.sh", timeout=300)
    print("[serial] shot script output:")
    print(result[-1500:])
    if "SHOTS_COMPLETE" not in result:
        print("[serial] WARN: shot script may not have completed")

    # ---------------- pull screenshots as base64 ----------------
    import os
    os.makedirs(shots_dir, exist_ok=True)
    listing = run_command(ser, "ls /tmp/lumo-shots/*.png 2>/dev/null", timeout=30)
    files = [f.strip() for f in listing.splitlines() if f.strip().endswith(".png")]
    print(f"[serial] pulling {len(files)} screenshots...")
    for path in files:
        name = path.rsplit("/", 1)[-1]
        run_command(ser, "", timeout=5)
        ser.sendline(f"base64 -w 4096 {path}")
        data = ""
        end = time.time() + 240
        while time.time() < end:
            ser.read_avail()
            chunk = ser.buf
            text = chunk.decode(errors="replace")
            if text.rstrip().endswith("PROMPT>") or "PROMPT>" in text[-30:]:
                data += text
                ser.buf = b""
                break
            data += text
            ser.buf = b""
            time.sleep(0.2)
        # strip prompt noise, keep base64 lines
        b64lines = [l.strip() for l in data.splitlines()
                    if l.strip() and not l.startswith("PROMPT>")
                    and not l.startswith("base64") and "PROMPT>" not in l
                    and not l.startswith("$")]
        try:
            raw = base64.b64decode("".join(b64lines), validate=False)
            with open(os.path.join(shots_dir, name), "wb") as fh:
                fh.write(raw)
            print(f"[serial] saved {name} ({len(raw)//1024} KB)")
        except Exception as exc:
            print(f"[serial] decode failed for {name}: {exc}")

    # ---------------- text reports ----------------
    print("[serial] === resource report ===")
    for cmd in ("free -m", "head -n 5 /proc/meminfo",
                "ps -eo rss,pid,comm --sort=-rss | head -n 14",
                "systemd-analyze 2>/dev/null", "cat /proc/uptime"):
        try:
            print(f"$ {cmd}")
            print(run_command(ser, cmd, timeout=60))
        except TimeoutError as exc:
            print(f"timeout: {exc}")

    print("SERIAL_DRIVER_COMPLETE")


if __name__ == "__main__":
    main()
