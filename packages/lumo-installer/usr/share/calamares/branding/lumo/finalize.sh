#!/bin/sh
# Lumo OS installer finalize hook.
# Calamares shellprocess runs this as root on the HOST with $ROOT pointing
# at the freshly installed system.
set -u
ROOT="${ROOT:-/tmp/calamares-root}"
[ -d "$ROOT/etc" ] || ROOT=$(ls -d /tmp/calamares-root-* 2>/dev/null | head -n1)
if [ ! -d "$ROOT/etc" ]; then
    echo "[lumo-finalize] cannot locate target root; skipping cleanup" >&2
    exit 0
fi

echo "[lumo-finalize] target root: $ROOT"

# 1) live-only bits must not leak into the installed system
rm -f "$ROOT/etc/sddm.conf.d/zz-live-autologin.conf"
rm -f "$ROOT/etc/sudoers.d/90-lumo-live"

# 2) purge installer + live infrastructure from the installed system
if [ -x "$ROOT/usr/bin/apt-get" ]; then
    mount --bind /dev     "$ROOT/dev"     2>/dev/null || true
    mount --bind /proc    "$ROOT/proc"    2>/dev/null || true
    mount --bind /sys     "$ROOT/sys"     2>/dev/null || true
    chroot "$ROOT" /bin/sh -c 'DEBIAN_FRONTEND=noninteractive apt-get -y purge \
        calamares "live-boot*" "live-config*" "live-tools" >/dev/null 2>&1 || true; \
        apt-get -y autoremove >/dev/null 2>&1 || true; apt-get clean' || true
    umount -l "$ROOT/sys" 2>/dev/null || true
    umount -l "$ROOT/proc" 2>/dev/null || true
    umount -l "$ROOT/dev" 2>/dev/null || true
fi

# 3) make sure the greeter + DM are active on the installed system
ln -sf /usr/lib/systemd/system/sddm.service "$ROOT/etc/systemd/system/display-manager.service" 2>/dev/null || true

echo "[lumo-finalize] done"
exit 0
