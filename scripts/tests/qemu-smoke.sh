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
# KVM when the runner provides /dev/kvm (GitHub ubuntu-24.04+ runners do):
# native CPU speed. TCG emulation runs the guest CPU 10-50x slower than the
# real clock, which blows GTK's frame deadlines and triggers a frame-clock
# recursion stack overflow in GTK4 (first paints miss every 16 ms deadline,
# the clock reschedules itself synchronously - seen in gdb backtraces as
# hundreds of identical libgtk-4 frames). KVM also makes the test 10x faster
# and behaves like real hardware.
if sudo -n test -e /dev/kvm 2>/dev/null || test -e /dev/kvm; then
  sudo -n chmod 666 /dev/kvm 2>/dev/null || true
fi
if test -w /dev/kvm; then
  ACCEL=(-accel kvm -cpu host)
  log "booting ISO in QEMU (KVM - native speed)"
else
  ACCEL=(-accel tcg,thread=multi -cpu max)
  log "booting ISO in QEMU (TCG fallback - no /dev/kvm)"
fi
rm -f "$BUILD_DIR/serial.log"
qemu-system-x86_64 \
  "${ACCEL[@]}" -smp 4 -m 3072 \
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
  "${SSHC[@]}" 'id
echo "--- sddm conf ---"
ls -la /etc/sddm.conf.d/ 2>/dev/null
cat /etc/sddm.conf.d/*.conf 2>/dev/null
echo "--- sddm unit ---"
systemctl is-active sddm; pgrep -a Xorg; pgrep -a labwc
echo "--- sddm journal ---"
journalctl -b -u sddm --no-pager 2>/dev/null | tail -n 40
echo "--- session logs ---"
ls -la /home/lumo/.local/share/sddm/ 2>/dev/null
cat /home/lumo/.local/share/sddm/*.log 2>/dev/null | tail -n 40
echo "--- journal lumo/labwc/wayland ---"
journalctl -b --no-pager 2>/dev/null | grep -iE "labwc|greeter|wayland|autolog" | tail -n 30
echo "--- test session unit ---"
systemctl status lumo-test-session --no-pager -l 2>/dev/null | tail -n 25
journalctl -b -u lumo-test-session --no-pager 2>/dev/null | tail -n 40
echo "--- session self-log ---"
cat /tmp/lumo-session.log 2>/dev/null | tail -n 50
echo "--- labwc sanity ---"
command -v labwc foot waybar dbus-run-session
labwc --version 2>&1 | head -n 2
ls -la /usr/share/lumo/session/ /usr/share/wayland-sessions/ 2>/dev/null' 2>/dev/null || true
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
  echo "== lumo sanity ==";   "${SSHC[@]}" 'ls /usr/share/lumo/theme/ 2>/dev/null; command -v lumo-launcher lumo-store lumo-settings; ls /usr/share/wayland-sessions/'
} > "$WORK/reports.txt" 2>&1 || true
cat "$WORK/reports.txt"

# ------------------------------------------ session RAM (honest metric)
# Measured BEFORE any test app is launched. PSS (proportional set size) of
# every process owned by the session user = the real "desktop session" RAM.
# Run as ROOT: kernel.yama.ptrace_scope=1 blocks same-uid reads of other
# processes' smaps_rollup (run 32 measured 18 MB because labwc/waybar were
# unreadable; the root-side serial report measured the true 109 MB).
log "measuring session RAM (PSS of session-user processes, idle, pre-apps)"
"${SSHC[@]}" 'cat > /tmp/lumo-ram.sh' <<'RAM' > /dev/null
LID=$(id -u lumo 2>/dev/null || echo 1000)
sync
echo 3 > /proc/sys/vm/drop_caches 2>/dev/null || true
sleep 2
SUM=0; N=0
for p in /proc/[0-9]*/smaps_rollup; do
  pid=${p%/smaps_rollup}; pid=${pid#/proc/}
  uid=$(stat -c %u "/proc/$pid" 2>/dev/null) || continue
  [ "$uid" = "$LID" ] || continue
  v=$(awk '/^Pss:/{print $2}' "$p" 2>/dev/null)
  [ -n "$v" ] && SUM=$((SUM+v)) && N=$((N+1))
done
echo "session_pss_kb: $SUM"
echo "session_procs: $N"
echo "== top session pss =="
for p in /proc/[0-9]*/smaps_rollup; do
  pid=${p%/smaps_rollup}; pid=${pid#/proc/}
  uid=$(stat -c %u "/proc/$pid" 2>/dev/null) || continue
  [ "$uid" = "$LID" ] || continue
  v=$(awk '/^Pss:/{print $2}' "$p" 2>/dev/null)
  [ -n "$v" ] && echo "$v $(cat /proc/$pid/comm 2>/dev/null) (pid $pid)"
done | sort -rn | head -n 14
echo "== zramctl =="
zramctl 2>/dev/null || true
echo "== free -m after drop_caches =="
free -m
RAM
{
  echo "== session ram (pss) =="
  "${SSHC[@]}" 'sudo -n sh /tmp/lumo-ram.sh 2>/dev/null || sh /tmp/lumo-ram.sh'
} >> "$WORK/reports.txt" 2>&1 || true
tail -n 25 "$WORK/reports.txt"

# ------------------------------------------------------- screenshots
log "capturing UI screenshots inside the guest"
"${SSHC[@]}" 'cat > /tmp/lumo-shots.sh' <<'EOS' > /dev/null
#!/bin/sh
export XDG_RUNTIME_DIR=/run/user/$(id -u)
export WAYLAND_DISPLAY=$(ls "$XDG_RUNTIME_DIR"/wayland-* 2>/dev/null | head -n1 | xargs -r basename)
export XDG_CURRENT_DESKTOP=lumo:wlroots
export HOME=/home/lumo
export GSK_RENDERER=cairo   # GTK4 GL renderer segfaults via llvmpipe (TCG/no-GPU)
export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"
SHOTS=/tmp/lumo-shots
STATUS="$SHOTS/status.txt"
rm -rf "$SHOTS"; mkdir -p "$SHOTS"; : > "$STATUS"
grim "$SHOTS/00-desktop.png" 2>"$SHOTS/00.err" || true

# shot <file> <timeout_s> <tag> <kill-pattern> <cmd...>
# launches the app and WAITS FOR THE REAL MAP EVENT (apps print LUMO_MAP_OK
# from their window 'map' handler). Under TCG emulation Python+GTK startup
# takes 5-15 s, so fixed sleeps shot before the window ever mapped.
shot() {
    f="$1"; timeout_s="$2"; tag="$3"; killpat="$4"; shift 4
    logf="/tmp/app-$tag.log"
    "$@" >"$logf" 2>&1 &
    p=$!
    waited=0; st=ALIVE; rc=""
    while :; do
        if grep -q LUMO_MAP_OK "$logf" 2>/dev/null; then
            sleep 1; break                       # first frame has landed
        fi
        if ! kill -0 "$p" 2>/dev/null; then
            st=DEAD
            wait "$p" 2>/dev/null; rc=$?        # real exit status (139 = segv)
            break
        fi
        if [ "$waited" -ge "$timeout_s" ]; then st=TIMEOUT; break; fi
        waited=$((waited+2)); sleep 2
    done
    echo "$f $st ${rc:+rc=$rc }$tag" >> "$STATUS"
    grim "$SHOTS/$f" 2>/dev/null || true
    kill "$p" 2>/dev/null || true
    pkill -f "$killpat" 2>/dev/null || true
    wait "$p" 2>/dev/null || true
}

# plain <file> <sleep_s> <tag> <kill-pattern> <cmd...> for apps that cannot
# print the marker (C programs, Qt)
plain() {
    f="$1"; wait_s="$2"; tag="$3"; killpat="$4"; shift 4
    logf="/tmp/app-$tag.log"
    "$@" >"$logf" 2>&1 &
    p=$!
    sleep "$wait_s"
    if kill -0 "$p" 2>/dev/null; then st=ALIVE; else st=DEAD; fi
    echo "$f $st $tag" >> "$STATUS"
    grim "$SHOTS/$f" 2>/dev/null || true
    kill "$p" 2>/dev/null || true
    pkill -f "$killpat" 2>/dev/null || true
    wait "$p" 2>/dev/null || true
}

shot 01-launcher.png       40 launcher lumo-launcher lumo-launcher
shot 02-quick-settings.png 40 qs       lumo-qs       lumo-qs
shot 03-calendar.png       40 calendar lumo-calendar lumo-calendar
shot 04-power.png          40 power    lumo-power    lumo-power
shot 05-store.png          90 store    lumo-store    lumo-store
shot 06-settings.png       60 settings lumo-settings lumo-settings
plain 07-terminal.png       3 terminal foot           foot

GREETER_BIN=$(command -v sddm-greeter 2>/dev/null || true)
[ -n "$GREETER_BIN" ] || GREETER_BIN=$(dpkg -L sddm 2>/dev/null | grep -E '^/usr/.*/sddm-greeter$' | head -n1)
[ -n "$GREETER_BIN" ] || GREETER_BIN=$(find /usr -name 'sddm-greeter*' -type f 2>/dev/null | head -n1)
echo "greeter binary: ${GREETER_BIN:-NOT FOUND}" >> "$STATUS"
echo "greeter candidates: $(dpkg -L sddm 2>/dev/null | grep -E '^/usr' | grep -iE 'greeter|/bin/' | tr '\n' ' ')" >> "$STATUS"
if [ -n "$GREETER_BIN" ] && [ -x "$GREETER_BIN" ]; then
    plain 08-greeter.png 8 greeter sddm-greeter env QT_QPA_PLATFORM=wayland "$GREETER_BIN" --test-mode --theme /usr/share/sddm/themes/lumo
else
    echo "08-greeter.png MISSING greeter" >> "$STATUS"
fi

# crash forensics: segfaults land in dmesg (GTK GL renderer on llvmpipe etc.)
echo "--- dmesg crashes (if any) ---"
sudo -n dmesg 2>/dev/null | grep -iE 'segfault|traps|oom|out of memory' | tail -n 20 || true

echo "--- status ---"
cat "$STATUS"
echo "--- app logs ---"
for f in /tmp/app-*.log; do echo "== $f =="; head -c 4000 "$f"; echo; done
echo SHOTS_COMPLETE
EOS
"${SSHC[@]}" 'chmod +x /tmp/lumo-shots.sh && /tmp/lumo-shots.sh' 2>&1 | tail -n 120
scp -q "${SSH_OPTS[@]/-p/-P}" 'lumo@127.0.0.1:/tmp/lumo-shots/*.png' "$SHOTS/" 2>/dev/null \
  || scp -q -P "$SSH_PORT" -i "$SSH_KEY" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
       'lumo@127.0.0.1:/tmp/lumo-shots/*.png' "$SHOTS/"
scp -q "${SSH_OPTS[@]/-p/-P}" 'lumo@127.0.0.1:/tmp/lumo-shots/status.txt' "$WORK/status.txt" 2>/dev/null \
  || scp -q -P "$SSH_PORT" -i "$SSH_KEY" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
       'lumo@127.0.0.1:/tmp/lumo-shots/status.txt' "$WORK/status.txt" || true
cat "$WORK/status.txt" 2>/dev/null || true
# crash forensics into the persisted reports (segfaults, oom, aborts)
{
  echo "== dmesg crashes =="
  "${SSHC[@]}" 'sudo -n dmesg 2>/dev/null | grep -iE "segfault|traps|oom|out of memory" | tail -n 25'
  echo "== coredumps =="
  "${SSHC[@]}" 'sudo -n coredumpctl list --no-pager 2>/dev/null | tail -n 10 || true'
} >> "$WORK/reports.txt" 2>&1 || true

# If apps segfaulted (rc=139): install gdb INSIDE the guest and get a real
# backtrace of one crashing app (stack-overflow recursion - top frame is
# arbitrary, the CYCLE is the evidence). Also try GTK_THEME=Adwaita to
# rule the Lumo CSS in or out.
if grep -q "rc=139" "$WORK/status.txt" 2>/dev/null; then
  log "installing gdb in the guest for backtraces (one-time, ~2-4 min under TCG)"
  "${SSHC[@]}" 'sudo -n apt-get update -qq 2>&1 | tail -n 2; sudo -n apt-get install -y -qq gdb 2>&1 | tail -n 2' || true
  "${SSHC[@]}" 'export XDG_RUNTIME_DIR=/run/user/$(id -u); export WAYLAND_DISPLAY=$(ls "$XDG_RUNTIME_DIR"/wayland-* 2>/dev/null | head -n1 | xargs -r basename); export GSK_RENDERER=cairo GTK_A11Y=none NO_AT_BRIDGE=1 HOME=/home/lumo DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus" DEBUGINFOD_URLS="https://debuginfod.debian.net";
    timeout 240 gdb -batch -iex "set debuginfod enabled on" -ex run -ex "bt 40" -ex "echo ===-FULL-BT-TAIL-===\n" -ex "bt -45" -ex "info proc mappings" --args /usr/bin/python3 /usr/libexec/lumo/lumo-settings > /tmp/gdb-settings.txt 2>&1; echo "gdb-settings rc=$?"
    tail -n 90 /tmp/gdb-settings.txt' | tail -n 95
  "${SSHC[@]}" 'export XDG_RUNTIME_DIR=/run/user/$(id -u); export WAYLAND_DISPLAY=$(ls "$XDG_RUNTIME_DIR"/wayland-* 2>/dev/null | head -n1 | xargs -r basename); export GSK_RENDERER=cairo GTK_A11Y=none NO_AT_BRIDGE=1 HOME=/home/lumo DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus" DEBUGINFOD_URLS="https://debuginfod.debian.net";
    timeout 240 gdb -batch -iex "set debuginfod enabled on" -ex run -ex "bt 40" -ex "echo ===-FULL-BT-TAIL-===\n" -ex "bt -45" --args /usr/bin/python3 /usr/libexec/lumo/lumo-launcher > /tmp/gdb-launcher.txt 2>&1; echo "gdb-launcher rc=$?"
    tail -n 90 /tmp/gdb-launcher.txt' | tail -n 95
  echo "== gdb backtraces ==" >> "$WORK/reports.txt"
  "${SSHC[@]}" 'cat /tmp/gdb-settings.txt /tmp/gdb-launcher.txt 2>/dev/null | tail -n 80' >> "$WORK/reports.txt" 2>&1 || true
  # experiment: does the Lumo CSS crash the launcher, or is it deeper?
  "${SSHC[@]}" 'export XDG_RUNTIME_DIR=/run/user/$(id -u); export WAYLAND_DISPLAY=$(ls "$XDG_RUNTIME_DIR"/wayland-* 2>/dev/null | head -n1 | xargs -r basename); export GSK_RENDERER=cairo GTK_A11Y=none NO_AT_BRIDGE=1 HOME=/home/lumo DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus" GTK_THEME=Adwaita;
    timeout 25 /usr/bin/lumo-launcher > /tmp/app-launcher-adw.log 2>&1; echo "launcher-adwaita rc=$?" >> /tmp/lumo-shots/status.txt;
    timeout 25 env GTK_THEME=Lumo /usr/bin/lumo-launcher > /tmp/app-launcher-lumo.log 2>&1; echo "launcher-lumo-theme rc=$?" >> /tmp/lumo-shots/status.txt' || true
  "${SSHC[@]}" 'grep -E "rc=" /tmp/lumo-shots/status.txt | tail -n 4; echo "--- adw log:"; head -c 800 /tmp/app-launcher-adw.log; echo; echo "--- lumo log:"; head -c 800 /tmp/app-launcher-lumo.log' || true
fi
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

def shot_ok(name, min_kb=12):
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

# liveness status written by the shot script (qtest/status.txt)
status = {}
for ln in read_file(os.path.join(build_dir, "qtest", "status.txt")).splitlines():
    parts = ln.split()
    if len(parts) >= 2 and parts[0].endswith(".png"):
        status[parts[0]] = parts[1]

import hashlib

def md5(path):
    try:
        with open(path, "rb") as fh:
            return hashlib.md5(fh.read()).hexdigest()
    except Exception:
        return None

all_hashes = {}
all_pngs = sorted(os.listdir(shots_dir)) if os.path.isdir(shots_dir) else []
for fn in all_pngs:
    if fn.endswith(".png"):
        h = md5(os.path.join(shots_dir, fn))
        if h:
            all_hashes.setdefault(h, []).append(fn)
dup_hashes = {h for h, fns in all_hashes.items() if len(fns) > 1}

boot_ok = "Lumo OS 1.0" in serial or "graphical.target" in serial or "Reached target" in serial
lumo_files_ok = "lumo-launcher" in reports and "apps-dark.css" in reports

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

# honest headline metric: PSS of the session user's processes (idle, pre-apps).
# Prefer the root-side measurement (serial console report) - see VALIDATION.md
# - and fall back to the SSH-side one; Yama can make the SSH-side undercount.
session_pss = None
ps = re.search(r"session_pss_kb:\s+(\d+)", reports)
if ps:
    session_pss = int(ps.group(1)) // 1024
ps2 = re.search(r"session_pss_kb:\s+(\d+)", serial)
if ps2 and (session_pss is None or int(ps2.group(1)) > session_pss * 1024):
    session_pss = int(ps2.group(1)) // 1024

cpu_idle = None
if "== idle cpu (5s) ==" in reports:
    cpu_sec = reports.split("== idle cpu (5s) ==")[1].split("==", 2)[0] if False else \
        reports.split("== idle cpu (5s) ==")[1]
    for line in cpu_sec.strip().splitlines():
        fields = line.split()
        if len(fields) >= 16 and all(re.fullmatch(r"\d+", f) for f in fields):
            cpu_idle = int(fields[14])  # vmstat 'id' column (0-based)

desktop_hash = md5(os.path.join(shots_dir, "00-desktop.png"))
for label, fname in checks:
    ok, detail = shot_ok(fname)
    st = status.get(fname, "UNKNOWN")
    if st == "DEAD":
        ok, detail = False, "app process exited before capture"
    elif st == "MISSING":
        ok, detail = False, "binary not found in guest"
    elif ok and fname != "00-desktop.png":
        h = md5(os.path.join(shots_dir, fname))
        if h and h == desktop_hash:
            ok, detail = False, "identical to desktop frame - window never rendered"
        elif h and h in dup_hashes:
            others = [x for x in all_hashes[h] if x != fname]
            ok, detail = False, f"pixel-identical to {', '.join(others)}"
    results[label] = ("PASS" if ok else "FAIL", detail)

ram_target = 150
if ram_idle is None:
    ram_verdict, ram_detail = "INFO", "meminfo not captured"
else:
    ram_verdict = "PASS" if ram_idle <= ram_target else ("NEAR" if ram_idle <= 250 else "MISS")
    ram_detail = f"{ram_idle} MB used (kernel + daemons + session, live media)"

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
if session_pss is None:
    lines.append("| Session RAM (idle, PSS of session processes) | INFO | smaps_rollup not captured |")
else:
    sv = "PASS" if session_pss <= ram_target else "FAIL"
    lines.append(f"| Session RAM (idle, PSS of session processes) | {sv} | {session_pss} MB (target <= {ram_target} MB) |")
lines.append(f"| System RAM (used, whole OS) | {ram_verdict} | {ram_detail} |")
lines.append(f"| CPU idle | {'PASS' if (cpu_idle or 0) >= 80 else 'INFO'} | ~{cpu_idle if cpu_idle is not None else '?'}% idle |")
lines.append("")
lines.append("## Warnings")
lines.append("")
lines.append("- Greeter screenshot uses `sddm-greeter --test-mode` inside the live session (approximation of the real greeter).")
lines.append("- Session RAM = sum of proportional set sizes (PSS) of the session user's processes, measured at idle before any test app runs.")
lines.append("- Duplicate-screenshot detection: any shot pixel-identical to the desktop frame fails the check (window never rendered).")
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
