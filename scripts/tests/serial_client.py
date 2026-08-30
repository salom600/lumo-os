#!/usr/bin/env python3
"""serial_client.py - drives the Lumo OS live guest through QEMU's stdio
serial (a FIFO for input, a followed log file for output).

Logs in as lumo over the console, prints diagnostics, waits for the
Wayland session, runs the in-guest screenshot script and streams the PNGs
back as base64. Network-independent by design.
"""
import argparse
import base64
import os
import socket
import sys
import time


class SerialIO:
    """FIFO writer + stream-file follower, with terminal query replies."""

    def __init__(self, fifo_path, stream_path):
        self.stream_path = stream_path
        self._fh = open(fifo_path, "wb", buffering=0)  # blocks until qemu reads
        self.buf = ""
        self._pos = 0

    def _reply_to_terminal_queries(self, text):
        if "\x1b[6n" in text:
            try:
                self._fh.write(b"\x1b[32766;32766R")
            except Exception:
                pass

    def pump(self):
        try:
            with open(self.stream_path, "r", errors="replace") as fh:
                fh.seek(self._pos)
                data = fh.read()
                self._pos = fh.tell()
        except FileNotFoundError:
            data = ""
        except Exception:
            data = ""
        if data:
            self._reply_to_terminal_queries(data)
            self.buf += data
            if len(self.buf) > 8 * 1024 * 1024:
                self.buf = self.buf[-4 * 1024 * 1024:]
        return data

    def read_until(self, patterns, timeout):
        end = time.time() + timeout
        while time.time() < end:
            self.pump()
            for p in patterns:
                idx = self.buf.find(p)
                if idx >= 0:
                    out = self.buf[: idx + len(p)]
                    self.buf = self.buf[idx + len(p):]
                    return out
            time.sleep(0.25)
        raise TimeoutError(f"serial timeout waiting for {patterns}; tail:\n{self.buf[-1500:]}")

    def send(self, text):
        try:
            self._fh.write(text.encode())
        except Exception as exc:
            print(f"[serial] write failed: {exc}")

    def sendline(self, line=""):
        # CR is the correct terminal Enter; guest icrnl translates to LF
        self.send(line + "\r")

    def drain(self, seconds=1.0):
        end = time.time() + seconds
        while time.time() < end:
            self.pump()
            time.sleep(0.1)
        out, self.buf = self.buf, ""
        return out


def run_command(ser, cmd, timeout=120):
    marker = f"CMDDONE{time.time_ns() % 100000}"
    ser.buf = ""
    ser.sendline(cmd + f"; echo {marker}")
    out = ser.read_until([marker], timeout)
    lines = out.splitlines()
    return "\n".join(lines[:-1])


SHOTS_SCRIPT = r"""#!/bin/sh
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

echo SHOTS_COMPLETE
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("shots_dir")
    ap.add_argument("--fifo", default=None)
    ap.add_argument("--stream", default=None)
    args = ap.parse_args()
    fifo = args.fifo or os.environ.get("SERIAL_FIFO", "/tmp/lumo-serial-in")
    stream = args.stream or os.environ.get("SERIAL_STREAM", "/tmp/lumo-serial.log")

    print("[serial] waiting for the login prompt (up to 12 min)...")
    ser = SerialIO(fifo, stream)

    logged_in = False
    for attempt in range(12):
        try:
            ser.read_until(["login:"], timeout=120)
        except TimeoutError:
            print(f"[serial] attempt {attempt}: no login prompt yet")
            continue
        time.sleep(2)
        ser.sendline("lumo")
        try:
            echo = ser.read_until(["Password:", "incorrect", "$ ", "# "], timeout=30)
        except TimeoutError:
            print(f"[serial] attempt {attempt}: prompt never advanced; tail:\n{ser.buf[-600:]}")
            ser.buf = ""
            continue
        if "incorrect" in echo:
            print(f"[serial] attempt {attempt}: login incorrect, retrying...")
            continue
        if "Password:" in echo:
            time.sleep(1)
            ser.sendline("lumo")
            try:
                echo2 = ser.read_until(["$ ", "# ", "incorrect", "Login"], timeout=30)
            except TimeoutError:
                print(f"[serial] attempt {attempt}: no shell prompt after password")
                continue
            if "incorrect" in echo2:
                print(f"[serial] attempt {attempt}: bad password, retrying...")
                continue
        logged_in = True
        break

    if not logged_in:
        print("[serial] FAIL: could not log in over serial")
        print(ser.drain(2)[-2500:])
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
    print("[serial] waiting for the Wayland session socket (up to 10 min)...")
    try:
        run_command(
            ser,
            "for i in $(seq 1 120); do test -S /run/user/$(id -u)/wayland-0 && break; "
            "test -S /run/user/$(id -u)/wayland-1 && break; sleep 5; done",
            timeout=700,
        )
        socks = run_command(ser, "ls /run/user/$(id -u)/ | grep wayland", timeout=30)
    except TimeoutError as exc:
        socks = ""
        print(f"[serial] session wait timed out: {exc}")
    print(f"[serial] sockets: {socks.strip() or 'NONE'}")
    if "wayland" not in socks:
        print("[serial] FAIL: no wayland socket; session diagnostics:")
        try:
            print(run_command(ser,
                "systemctl status display-manager --no-pager -l 2>/dev/null | tail -n 30; "
                "journalctl -b --no-pager 2>/dev/null | grep -iE 'labwc|sddm|greeter|wayland' | tail -n 40",
                timeout=90))
        except TimeoutError:
            print("diagnostics timed out")
        sys.exit(1)

    # ---------------- screenshots inside the guest ----------------
    print("[serial] transferring and running the screenshot script...")
    ser.sendline("cat > /tmp/lumo-shots.sh << 'SHOTSEOF'")
    for line in SHOTS_SCRIPT.splitlines():
        ser.sendline(line)
        time.sleep(0.01)
    ser.sendline("SHOTSEOF")
    try:
        ser.read_until(["SHOTSEOF"], timeout=60)
    except TimeoutError:
        pass
    run_command(ser, "chmod +x /tmp/lumo-shots.sh", timeout=30)
    result = run_command(ser, "/tmp/lumo-shots.sh", timeout=300)
    print("[serial] shot script output:")
    print(result[-1200:])
    if "SHOTS_COMPLETE" not in result:
        print("[serial] WARN: shot script may not have completed")

    # ---------------- pull screenshots as base64 ----------------
    os.makedirs(args.shots_dir, exist_ok=True)
    listing = run_command(ser, "ls /tmp/lumo-shots/*.png 2>/dev/null", timeout=30)
    files = [f.strip().replace("PROMPT>", "").strip() for f in listing.splitlines()
             if f.strip().endswith(".png")]
    print(f"[serial] pulling {len(files)} screenshots...")
    for path in files:
        name = path.rsplit("/", 1)[-1]
        ser.sendline(f"base64 -w 4096 {path}")
        data = ""
        end = time.time() + 240
        while time.time() < end:
            ser.pump()
            if "PROMPT>" in ser.buf[-20:]:
                data += ser.buf
                ser.buf = ""
                break
            data += ser.buf
            ser.buf = ""
            time.sleep(0.2)
        b64lines = [l.strip() for l in data.splitlines()
                    if l.strip() and "PROMPT>" not in l
                    and not l.strip().startswith("base64")
                    and not l.strip().endswith(str(path))]
        try:
            raw = base64.b64decode("".join(b64lines), validate=False)
            if len(raw) > 1024:
                with open(os.path.join(args.shots_dir, name), "wb") as fh:
                    fh.write(raw)
                print(f"[serial] saved {name} ({len(raw)//1024} KB)")
            else:
                print(f"[serial] {name}: too small ({len(raw)} bytes), skipped")
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
