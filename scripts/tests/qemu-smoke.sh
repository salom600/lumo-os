#!/usr/bin/env bash
# qemu-smoke.sh - automated boot test + UI screenshots + RAM/CPU report.
# Boots the ISO with the live test mode (lumo.test=1) and validates the
# session over SSH, producing build/validation-report.md + screenshots.
set -uo pipefail

ISO="${1:?usage: qemu-smoke.sh <iso>}"
BUILD_DIR="$(cd "$(dirname "$0")/../.." && pwd)/build"
WORK="$BUILD_DIR/qtest"
SHOTS="$BUILD_DIR/screenshots"
mkdir -p "$WORK" "$SHOTS"

SSH_PORT=2222
SSH_KEY="$WORK/test_key"
SSH_OPTS=(-p "$SSH_PORT" -i "$SSH_KEY" -o StrictHostKeyChecking=no
          -o UserKnownHostsFile=/dev/null -o ConnectTimeout=10 -o LogLevel=ERROR)
SSH_TARGET="lumo@127.0.0.1"
SSHC=(ssh "${SSH_OPTS[@]}" "$SSH_TARGET")
SCPOPTS=(-P "$SSH_PORT" -i "$SSH_KEY" -o StrictHostKeyChecking=no
         -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR)

log() { echo "[smoke] $*"; }

cleanup() {
  [ -n "${QEMU_PID:-}" ] && kill "$QEMU_PID" 2>/dev/null || true
}
trap cleanup EXIT

# ---------------------------------------------------------------- key
rm -f "$SSH_KEY" "$SSH_KEY.pub"
ssh-keygen -t ed25519 -N "" -f "$SSH_KEY" -q
PUBKEY_B64="$(base64 -w0 "$SSH_KEY.pub")"

# ------------------------------------------------- extract kernel/initrd
log "extracting kernel + initrd from ISO"
KDIR="$WORK/iso"
mkdir -p "$KDIR"
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
log "booting ISO in QEMU (TCG) with lumo.test=1"
qemu-system-x86_64 \
  -accel tcg,thread=multi -cpu max -smp 4 -m 3072 \
  -kernel "$KDIR/vmlinuz" -initrd "$KDIR/initrd" \
  -append "boot=live components console=ttyS0 lumo.test=1 lumo.pubkey=${PUBKEY_B64} quiet" \
  -cdrom "$ISO" -no-reboot -display none \
  -device virtio-net-pci,netdev=n0 -netdev "user,id=n0,hostfwd=tcp:127.0.0.1:${SSH_PORT}-:22" \
  -serial "file:$BUILD_DIR/serial.log" &
QEMU_PID=$!

# ------------------------------------------------------------ wait ssh
# NOTE: with QEMU user-mode hostfwd, the host-side port accepts connections
# as soon as QEMU starts, so a plain `nc -z` is meaningless. Use real SSH
# handshakes instead.
log "waiting for SSH (up to ~30 min under TCG)"
SSH_UP=0
for i in $(seq 1 90); do
  if "${SSHC[@]}" 'echo ok' 2>/dev/null | grep -q ok; then SSH_UP=1; break; fi
  if ! kill -0 "$QEMU_PID" 2>/dev/null; then log "QEMU died early"; break; fi
  sleep 20
done
if [ "$SSH_UP" != 1 ]; then
  log "FAIL: SSH never came up; last serial output:"
  tail -n 80 "$BUILD_DIR/serial.log" 2>/dev/null || true
  exit 1
fi
log "SSH is up after ~$((i*20/60)) minutes"

# ----------------------------------------------------- wait for session
log "waiting for the Wayland session (autologin, up to ~33 min)"
SESSION_UP=0
for i in $(seq 1 100); do
  if "${SSHC[@]}" 'test -S /run/user/$(id -u)/wayland-0 || test -S /run/user/$(id -u)/wayland-1' 2>/dev/null; then
    SESSION_UP=1; break
  fi
  if ! kill -0 "$QEMU_PID" 2>/dev/null; then break; fi
  sleep 20
done
if [ "$SESSION_UP" != 1 ]; then
  log "FAIL: desktop session never appeared; diagnostics:"
  "${SSHC[@]}" 'systemctl --failed --no-legend; systemctl status display-manager --no-pager -l | tail -n 25; journalctl -b -p err --no-pager | tail -n 40; ls -la /run/user/$(id -u)/ 2>/dev/null' 2>/dev/null || true
  tail -n 60 "$BUILD_DIR/serial.log" 2>/dev/null || true
  exit 1
fi
log "Wayland session detected"

# ---------------------------------------------------------- reports
log "collecting resource + system reports"
{
  echo "== date ==";        "${SSHC[@]}" date
  echo "== free -m ==";     "${SSHC[@]}" free -m
  echo "== meminfo ==";     "${SSHC[@]}" head -n 5 /proc/meminfo
  echo "== idle cpu (5s) =="; "${SSHC[@]}" vmstat 1 5 2>/dev/null | tail -n 2
  echo "== failed units ==";  "${SSHC[@]}" systemctl --failed --no-legend --no-pager
  echo "== boot time ==";     "${SSHC[@]}" systemd-analyze 2>/dev/null
  echo "== uptime ==";        "${SSHC[@]}" cat /proc/uptime
  echo "== session procs =="; "${SSHC[@]}" ps -eo rss,pid,comm --sort=-rss | head -n 14
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
shot() { sleep 2; grim "$SHOTS/$1.png" 2>/dev/null || echo "grim failed: $1"; }

shot 00-desktop

lumo-launcher >/dev/null 2>&1 & sleep 3; shot 01-launcher;  pkill -f lumo-launcher 2>/dev/null
lumo-qs       >/dev/null 2>&1 & sleep 3; shot 02-quick-settings; pkill -f lumo-qs 2>/dev/null
lumo-calendar >/dev/null 2>&1 & sleep 2; shot 03-calendar; pkill -f lumo-calendar 2>/dev/null
lumo-power    >/dev/null 2>&1 & sleep 2; shot 04-power;   pkill -f lumo-power 2>/dev/null
lumo-store    >/dev/null 2>&1 & sleep 7; shot 05-store;   pkill -f lumo-store 2>/dev/null
lumo-settings >/dev/null 2>&1 & sleep 6; shot 06-settings; pkill -f lumo-settings 2>/dev/null
foot          >/dev/null 2>&1 & sleep 3; shot 07-terminal; pkill -f foot 2>/dev/null

QT_QPA_PLATFORM=wayland sddm-greeter --test-mode --theme /usr/share/sddm/themes/lumo \
  >/tmp/greeter.log 2>&1 &
sleep 5; shot 08-greeter; pkill -f sddm-greeter 2>/dev/null

ls -la "$SHOTS"
EOS
"${SSHC[@]}" 'chmod +x /tmp/lumo-shots.sh && /tmp/lumo-shots.sh'
scp -q "${SCPOPTS[@]}" 'lumo@127.0.0.1:/tmp/lumo-shots/*.png' "$SHOTS/"

ls -la "$SHOTS"

# -------------------------------------------------------- validation
log "validating screenshots and writing report"
python3 - "$BUILD_DIR" "$GITHUB_RUN_NUMBER" <<'EOP'
import os, re, sys

build_dir = sys.argv[1]
run_no = sys.argv[2] if len(sys.argv) > 2 else "local"
shots_dir = os.path.join(build_dir, "screenshots")
reports_path = os.path.join(build_dir, "qtest", "reports.txt")
serial_path = os.path.join(build_dir, "serial.log")

try:
    from PIL import Image
except Exception:
    Image = None

def shot_ok(name, min_kb=25):
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
            if hi - lo < 12:
                return False, "image appears blank/uniform"
        except Exception as e:
            return False, f"unreadable: {e}"
    return True, f"{os.path.getsize(p)//1024} KB"

checks = [
    ("boot",               None, None),
    ("login (autologin)",  None, None),
    ("desktop shell",      "00-desktop.png", "waybar bar + dock + wallpaper"),
    ("app launcher",       "01-launcher.png", "lumo-launcher overlay"),
    ("quick settings",     "02-quick-settings.png", "lumo-qs panel"),
    ("calendar popup",     "03-calendar.png", "lumo-calendar"),
    ("power dialog",       "04-power.png", "lumo-power"),
    ("app store",          "05-store.png", "lumo-store"),
    ("settings",           "06-settings.png", "lumo-settings"),
    ("terminal",           "07-terminal.png", "foot"),
    ("greeter",            "08-greeter.png", "SDDM Lumo theme (test-mode)"),
]

results = {}
serial = ""
try:
    with open(serial_path, errors="ignore") as fh:
        serial = fh.read()
except Exception:
    pass
reports = ""
try:
    with open(reports_path, errors="ignore") as fh:
        reports = fh.read()
except Exception:
    pass

results["boot"] = ("PASS" if ("LUMO OS RESOURCE REPORT" in serial or "Reached target" in serial
                              or "Welcome to" in serial) else "FAIL",
                   "serial console evidence")
ram_idle = None
m = re.search(r"MemTotal:\s+(\d+) kB", reports)
a = re.search(r"MemAvailable:\s+(\d+) kB", reports)
if m and a:
    ram_idle = (int(m.group(1)) - int(a.group(1))) // 1024
cpu_idle = None
cpu_sec = ""
if "== idle cpu (5s) ==" in reports:
    cpu_sec = reports.split("== idle cpu (5s) ==")[1].split("== failed units ==")[0]
    for line in cpu_sec.strip().splitlines():
        fields = line.split()
        if len(fields) >= 16 and all(re.fullmatch(r"\d+", f) for f in fields):
            cpu_idle = int(fields[13])  # vmstat 'id' column

for label, fname, _desc in checks:
    if fname is None:
        continue
    ok, detail = shot_ok(fname)
    results[label] = ("PASS" if ok else "FAIL", detail)
if "LUMO OS RESOURCE REPORT" in serial:
    results["ram/cpu report"] = ("PASS", "serial report captured")
if "login (autologin)" not in results:
    results["login (autologin)"] = ("PASS" if results.get("desktop shell", ("FAIL",))[0] == "PASS" else "FAIL",
                                    "inferred from desktop session")

ram_target = 150
ram_verdict = "PASS" if (ram_idle is not None and ram_idle <= ram_target) else ("NEAR" if ram_idle and ram_idle <= 250 else "MISS")

lines = []
lines.append(f"# Lumo OS Validation Report (run {run_no})")
lines.append("")
lines.append("| Check | Result | Details |")
lines.append("|---|---|---|")
for label, _f, _d in checks:
    if label == "boot":
        continue
    if label == "login (autologin)":
        res, det = results["login (autologin)"]
        lines.append(f"| login screen (live autologin) | {res} | {det} |")
        continue
    res, det = results.get(label, ("FAIL", "not captured"))
    lines.append(f"| {label} | {res} | {det} |")
lines.append(f"| boot | {results['boot'][0]} | {results['boot'][1]} |")
lines.append(f"| RAM usage (idle session) | {ram_verdict} | {ram_idle} MB used (target: < {ram_target} MB) |")
lines.append(f"| CPU idle | {'PASS' if (cpu_idle or 0) >= 85 else 'INFO'} | ~{cpu_idle if cpu_idle is not None else '?'}% idle |")
lines.append("")
lines.append("## Warnings")
lines.append("")
lines.append("- Store listing requires AppStream metadata; if empty, click 'Check for updates' (RefreshCache).")
lines.append("- Greeter screenshot uses sddm-greeter --test-mode inside the live session (an approximation of the real greeter).")
lines.append("")
with open(os.path.join(build_dir, "validation-report.md"), "w") as fh:
    fh.write("\n".join(lines))
print("\n".join(lines))

fails = [k for k, (v, _d) in results.items() if v == "FAIL"]
print(f"\nSMOKE RESULT: {'PASS' if not fails else 'FAIL: ' + ', '.join(fails)}")
sys.exit(0 if not fails else 1)
EOP
SMOKE_RC=$?

log "done (rc=$SMOKE_RC)"
exit $SMOKE_RC
