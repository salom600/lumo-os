#!/usr/bin/env bash
# qemu-smoke.sh - automated boot test: boots the ISO with lumo.test=1,
# validates the session over SSH (serial console as fallback/log), captures
# screenshots of every shell surface, collects RAM/CPU reports and writes
# build/validation-report.md.
set -uo pipefail

ISO="${1:?usage: qemu-smoke.sh <iso>}"
HERE="$(cd "$(dirname "$0")/../.." && pwd)"
BUILD_DIR="$HERE/build"
WORK="$BUILD_DIR/qtest"
SHOTS="$BUILD_DIR/screenshots"
mkdir -p "$WORK" "$SHOTS"

SSH_PORT=2222
SSH_KEY="$WORK/test_key"
SSH_OPTS=(-p "$SSH_PORT" -i "$SSH_KEY" -o StrictHostKeyChecking=no
          -o UserKnownHostsFile=/dev/null -o ConnectTimeout=15 -o LogLevel=ERROR -o BatchMode=yes)
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
log "booting ISO in QEMU (TCG)"
rm -f "$BUILD_DIR/serial.log"
qemu-system-x86_64 \
  -accel tcg,thread=multi -cpu max -smp 4 -m 3072 \
  -kernel "$KDIR/vmlinuz" -initrd "$KDIR/initrd" \
  -append "boot=live components console=ttyS0 lumo.test=1 lumo.pubkey=${PUBKEY_B64} systemd.show_status=1" \
  -cdrom "$ISO" -no-reboot -display none -monitor none \
  -device e1000,netdev=n0 -netdev "user,id=n0,hostfwd=tcp:127.0.0.1:${SSH_PORT}-:22" \
  -serial stdio \
  < /dev/null > "$BUILD_DIR/serial.log" 2> "$WORK/qemu-err.log" &
QEMU_PID=$!

# ------------------------------------------------------------ wait SSH
# (hostfwd accepts TCP immediately, so use real handshakes)
log "waiting for SSH (up to ~30 min under TCG)"
SSH_UP=0
for i in $(seq 1 90); do
  if "${SSHC[@]}" 'echo ok' 2>/dev/null | grep -q ok; then SSH_UP=1; break; fi
  if ! kill -0 "$QEMU_PID" 2>/dev/null; then log "QEMU died early"; break; fi
  sleep 20
done

if [ "$SSH_UP" != 1 ]; then
  log "SSH unavailable - falling back to the serial driver"
  python3 "$HERE/scripts/tests/serial_client.py" "$SHOTS" \
    --fifo "$WORK/serial-in" --stream "$BUILD_DIR/serial.log" \
    2>&1 | tee "$BUILD_DIR/serial-session.log" || true
  log "serial driver done; validation will use whatever it captured"
  python3 - "$BUILD_DIR" "${GITHUB_RUN_NUMBER:-local}" <<'EOP'
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/../tests")
print("serial fallback path: reports only; see artifact serial-session.log")
EOP
  exit 1
fi
log "SSH is up after ~$((i*20/60)) minutes"

# ------------------------------------------------- wait for the session
log "waiting for the Wayland session (autologin, up to ~20 min)"
SESSION_UP=0
for i in $(seq 1 60); do
  if "${SSHC[@]}" 'test -S /run/user/$(id -u)/wayland-0 || test -S /run/user/$(id -u)/wayland-1' 2>/dev/null; then
    SESSION_UP=1; break
  fi
  sleep 20
done
if [ "$SESSION_UP" != 1 ]; then
  log "FAIL: desktop session never appeared; diagnostics:"
  "${SSHC[@]}" 'id; systemctl --failed --no-legend --no-pager; systemctl status sddm --no-pager -l 2>/dev/null | tail -n 20; journalctl -b --no-pager 2>/dev/null | grep -iE "labwc|sddm|greeter|wayland|lumo" | tail -n 50; ls -la /run/user/$(id -u)/ 2>/dev/null' 2>/dev/null || true
  exit 1
fi
log "Wayland session detected"

# ---------------------------------------------------------- reports
log "collecting resource + system reports"
{
  echo "== date ==";          "${SSHC[@]}" date
  echo "== free -m ==";       "${SSHC[@]}" free -m
  echo "== meminfo ==";       "${SSHC[@]}" head -n 5 /proc/meminfo
  echo "== idle cpu (5s) =="; "${SSHC[@]}" vmstat 1 5 2>/dev/null | tail -n 2
  echo "== failed units ==";  "${SSHC[@]}" systemctl --failed --no-legend --no-pager
  echo "== boot time ==";     "${SSHC[@]}" systemd-analyze 2>/dev/null
  echo "== uptime ==";        "${SSHC[@]}" cat /proc/uptime
  echo "== session procs =="; "${SSHC[@]}" ps -eo rss,pid,comm --sort=-rss | head -n 16
  echo "== lumo sanity ==";   "${SSHC[@]}" 'ls /usr/share/lumo/theme /usr/bin/lumo-* 2>/dev/null | head -n 20; systemctl is-active sddm NetworkManager'
} > "$WORK/reports.txt" 2>&1 || true
cat "$WORK/reports.txt"

# ------------------------------------------------------- screenshots
log "capturing UI screenshots inside the guest"
"${SSHC[@]}" 'cat > /tmp/lumo-shots.sh' <<'EOS' > /dev/null
#!/bin/sh
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
EOS
"${SSHC[@]}" 'chmod +x /tmp/lumo-shots.sh && /tmp/lumo-shots.sh' 2>&1 | tail -n 5
scp -q "${SSH_OPTS[@]/-p/-P}" 'lumo@127.0.0.1:/tmp/lumo-shots/*.png' "$SHOTS/" 2>/dev/null \
  || scp -q -P "$SSH_PORT" -i "$SSH_KEY" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
       'lumo@127.0.0.1:/tmp/lumo-shots/*.png' "$SHOTS/"
"${SSHC[@]}" 'cat /tmp/lumo-shots/00.err /tmp/greeter.log 2>/dev/null | head -n 20' || true
ls -la "$SHOTS"

# -------------------------------------------------------- validation
log "validating screenshots and writing report"
python3 - "$BUILD_DIR" "${GITHUB_RUN_NUMBER:-local}" <<'EOP'
import os, re, sys

build_dir = sys.argv[1]
run_no = sys.argv[2] if len(sys.argv) > 2 else "local"
shots_dir = os.path.join(build_dir, "screenshots")
reports_path = os.path.join(build_dir, "qtest", "reports.txt")
serial_log = os.path.join(build_dir, "serial.log")

try:
    from PIL import Image
except Exception:
    Image = None

def read_file(p):
    try:
        with open(p, errors="ignore") as fh:
            return fh.read()
    except Exception:
        return ""

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

reports = read_file(reports_path)
serial = read_file(serial_log)

boot_ok = "Lumo OS 1.0" in serial or "graphical.target" in serial or "Reached target" in serial
lumo_files_ok = "lumo-session" in reports and "rc.xml" in reports

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
results["lumo packages present"] = ("PASS" if lumo_files_ok else "FAIL",
                                    "theme/session files in guest")

ram_idle = None
m = re.search(r"MemTotal:\s+(\d+) kB", reports)
a = re.search(r"MemAvailable:\s+(\d+) kB", reports)
if m and a:
    ram_idle = (int(m.group(1)) - int(a.group(1))) // 1024

cpu_idle = None
if "== idle cpu (5s) ==" in reports:
    cpu_sec = reports.split("== idle cpu (5s) ==")[1].split("==", 2)[0] if False else \
        reports.split("== idle cpu (5s) ==")[1]
    for line in cpu_sec.strip().splitlines():
        fields = line.split()
        if len(fields) >= 16 and all(re.fullmatch(r"\d+", f) for f in fields):
            cpu_idle = int(fields[13])  # vmstat 'id' column

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
lines.append(f"| lumo packages present | {results['lumo packages present'][0]} | {results['lumo packages present'][1]} |")
for label, _f in checks:
    res, det = results[label]
    lines.append(f"| {label} | {res} | {det} |")
lines.append(f"| RAM usage (idle session) | {ram_verdict} | {ram_detail} |")
lines.append(f"| CPU idle | {'PASS' if (cpu_idle or 0) >= 80 else 'INFO'} | ~{cpu_idle if cpu_idle is not None else '?'}% idle |")
lines.append("")
lines.append("## Warnings")
lines.append("")
lines.append("- Greeter screenshot uses `sddm-greeter --test-mode` inside the live session (approximation of the real greeter).")
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

log "done (validation rc=$VALID_RC)"
exit $VALID_RC
