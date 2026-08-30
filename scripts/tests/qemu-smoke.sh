#!/usr/bin/env bash
# qemu-smoke.sh - automated boot test driven over the QEMU serial console.
# Boots the ISO with lumo.test=1, logs in as lumo (serial), captures
# screenshots of every shell surface, collects RAM/CPU reports and writes
# build/validation-report.md. Network-independent.
set -uo pipefail

ISO="${1:?usage: qemu-smoke.sh <iso>}"
HERE="$(cd "$(dirname "$0")/../.." && pwd)"
BUILD_DIR="$HERE/build"
WORK="$BUILD_DIR/qtest"
SHOTS="$BUILD_DIR/screenshots"
mkdir -p "$WORK" "$SHOTS"

SER_PORT=4555
SSH_PORT=2222
SSH_KEY="$WORK/test_key"
SSH_OPTS=(-p "$SSH_PORT" -i "$SSH_KEY" -o StrictHostKeyChecking=no
          -o UserKnownHostsFile=/dev/null -o ConnectTimeout=10 -o LogLevel=ERROR)
SSHC=(ssh "${SSH_OPTS[@]}" "lumo@127.0.0.1")

log() { echo "[smoke] $*"; }

cleanup() {
  [ -n "${QEMU_PID:-}" ] && kill "$QEMU_PID" 2>/dev/null || true
}
trap cleanup EXIT

rm -f "$SSH_KEY" "$SSH_KEY.pub"
ssh-keygen -t ed25519 -N "" -f "$SSH_KEY" -q
PUBKEY_B64="$(base64 -w0 "$SSH_KEY.pub")"

# ------------------------------------------------- extract kernel/initrd
log "extracting kernel + initrd from ISO"
KDIR="$WORK/iso"
rm -rf "$KDIR"; mkdir -p "$KDIR"
if sudo mount -o loop,ro "$ISO" /mnt 2>/dev/null; then
  cp /mnt/live/vmlinuz "$KDIR/vmlinuz"
  cp /mnt/live/initrd  "$KDIR/initrd"
  sudo umount /mnt
else
  log "loop mount failed; falling back to xorriso extraction"
  xorriso -osirrox on -indev "$ISO" -extract /live "$KDIR" >/dev/null 2>&1
fi
ls -la "$KDIR"

# ---------------------------------------------------------------- boot
log "booting ISO in QEMU (TCG), serial on stdio via FIFO"
rm -f "$BUILD_DIR/serial.log" "$WORK/serial-in"
mkfifo "$WORK/serial-in"
qemu-system-x86_64 \
  -accel tcg,thread=multi -cpu max -smp 4 -m 3072 \
  -kernel "$KDIR/vmlinuz" -initrd "$KDIR/initrd" \
  -append "boot=live components console=ttyS0 lumo.test=1 lumo.pubkey=${PUBKEY_B64} systemd.show_status=1" \
  -cdrom "$ISO" -no-reboot -display none -monitor none \
  -device e1000,netdev=n0 -netdev "user,id=n0,hostfwd=tcp:127.0.0.1:${SSH_PORT}-:22" \
  -serial stdio \
  < "$WORK/serial-in" > "$BUILD_DIR/serial.log" 2> "$WORK/qemu-err.log" &
QEMU_PID=$!

# ------------------------------------------------- serial-driven session
log "driving the guest over the serial console (login, shots, reports)"
python3 "$HERE/scripts/tests/serial_client.py" "$SHOTS" \
  --fifo "$WORK/serial-in" --stream "$BUILD_DIR/serial.log" \
  2>&1 | tee "$BUILD_DIR/serial-session.log"
SERIAL_RC=${PIPESTATUS[0]}
log "serial driver finished (rc=$SERIAL_RC)"

# --------------------------------------------------- bonus: SSH check
SSH_NOTE="serial-only (guest networking unverified)"
log "checking whether guest SSH is also reachable..."
for i in $(seq 1 10); do
  if "${SSHC[@]}" 'echo ok' 2>/dev/null | grep -q ok; then
    SSH_NOTE="SSH reachable"
    "${SSHC[@]}" 'free -m; ip -4 addr show' > "$WORK/ssh-report.txt" 2>&1 || true
    break
  fi
  sleep 10
done
log "guest ssh: $SSH_NOTE"

# -------------------------------------------------------- validation
log "validating screenshots and writing report"
python3 - "$BUILD_DIR" "${GITHUB_RUN_NUMBER:-local}" <<'EOP'
import os, re, sys

build_dir = sys.argv[1]
run_no = sys.argv[2] if len(sys.argv) > 2 else "local"
shots_dir = os.path.join(build_dir, "screenshots")
session_log = os.path.join(build_dir, "serial-session.log")
serial_log = os.path.join(build_dir, "serial.log")

try:
    from PIL import Image
except Exception:
    Image = None

def shot_ok(name, min_kb=20):
    p = os.path.join(shots_dir, name)
    if not os.path.exists(p):
        return False, "missing"
    if os.path.getsize(p) < min_kb * 1024:
        return False, f"only {os.path.getsize(p)//1024} KB"
    if Image is not None:
        try:
            img = Image.open(p).convert("L")
            small = img.resize((64, 36))
            lo, hi = min(small.getdata()), max(small.getdata())
            if hi - lo < 10:
                return False, "image appears blank/uniform"
        except Exception as e:
            return False, f"unreadable: {e}"
    return True, f"{os.path.getsize(p)//1024} KB"

def read_file(p):
    try:
        with open(p, errors="ignore") as fh:
            return fh.read()
    except Exception:
        return ""

session = read_file(session_log)
serial = read_file(serial_log)

boot_ok = "Lumo OS 1.0" in serial or "Lumo OS 1.0" in session or "Reached target" in serial
login_ok = "logged in as lumo" in session
testmode_ok = "TEST_MODE_OK" in session

checks = [
    ("desktop shell",  "00-desktop.png"),
    ("app launcher",   "01-launcher.png"),
    ("quick settings", "02-quick-settings.png"),
    ("calendar popup", "03-calendar.png"),
    ("power dialog",   "04-power.png"),
    ("app store",      "05-store.png"),
    ("settings",       "06-settings.png"),
    ("terminal",       "07-terminal.png"),
    ("greeter (test-mode preview)", "08-greeter.png"),
]

results = {}
results["boot"] = ("PASS" if boot_ok else "FAIL", "serial boot evidence")
results["login (serial autologin by driver)"] = ("PASS" if login_ok else "FAIL",
                                                 "console login as lumo")
results["live test mode"] = ("PASS" if testmode_ok else "WARN",
                             "lumo-live-setup test marker")

ram_idle = None
m = re.search(r"MemTotal:\s+(\d+) kB", session)
a = re.search(r"MemAvailable:\s+(\d+) kB", session)
if m and a:
    ram_idle = (int(m.group(1)) - int(a.group(1))) // 1024

cpu_idle = None
mm = re.search(r"\$ cat /proc/uptime\n([\d.]+) ", session)
uptime = float(mm.group(1)) if mm else None

for label, fname in checks:
    ok, detail = shot_ok(fname)
    results[label] = ("PASS" if ok else "FAIL", detail)

ram_target = 150
if ram_idle is None:
    ram_verdict, ram_detail = "INFO", "meminfo not captured"
else:
    ram_verdict = "PASS" if ram_idle <= ram_target else ("NEAR" if ram_idle <= 250 else "MISS")
    ram_detail = f"{ram_idle} MB used (target < {ram_target} MB)"

lines = []
lines.append(f"# Lumo OS Validation Report (run {run_no})")
lines.append("")
lines.append("| Check | Result | Details |")
lines.append("|---|---|---|")
lines.append(f"| boot | {results['boot'][0]} | {results['boot'][1]} |")
lines.append(f"| login (live, test mode) | {results['login (serial autologin by driver)'][0]} | {results['login (serial autologin by driver)'][1]} |")
for label, _f in checks:
    res, det = results[label]
    lines.append(f"| {label} | {res} | {det} |")
lines.append(f"| RAM usage (idle session) | {ram_verdict} | {ram_detail} |")
lines.append(f"| guest uptime at report | INFO | {uptime if uptime else '?'} s |")
lines.append("")
lines.append("## Warnings")
lines.append("")
lines.append("- Greeter screenshot uses `sddm-greener --test-mode` inside the live session (approximation of the real greeter).")
lines.append("- Store listing requires AppStream metadata; if empty, use Updates > Check (RefreshCache).")
lines.append("")
with open(os.path.join(build_dir, "validation-report.md"), "w") as fh:
    fh.write("\n".join(lines))
print("\n".join(lines))

fails = [k for k, (v, _d) in results.items() if v == "FAIL"]
print(f"\nSMOKE RESULT: {'PASS' if not fails else 'FAIL: ' + ', '.join(fails)}")
sys.exit(0 if not fails else 1)
EOP
VALID_RC=$?

log "done (serial rc=$SERIAL_RC, validation rc=$VALID_RC)"
exit $VALID_RC
