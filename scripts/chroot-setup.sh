#!/usr/bin/env bash
# chroot-setup.sh - runs INSIDE the rootfs chroot (cwd = /)
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

echo "[lumo] installing Lumo packages"
dpkg -i /root/lumo-debs/*.deb || apt-get -f install -y
dpkg -i /root/lumo-debs/*.deb   # second pass: resolve inter-package deps

echo "[lumo] generating locales (en + Arabic for RTL)"
sed -i 's/^# *en_US.UTF-8 UTF-8/en_US.UTF-8 UTF-8/' /etc/locale.gen
sed -i 's/^# *ar_EG.UTF-8 UTF-8/ar_EG.UTF-8 UTF-8/' /etc/locale.gen
sed -i 's/^# *ar_SA.UTF-8 UTF-8/ar_SA.UTF-8 UTF-8/' /etc/locale.gen
locale-gen

echo "[lumo] identity"
echo "lumo" > /etc/hostname
cat > /etc/hosts <<'EOF'
127.0.0.1	localhost
127.0.1.1	lumo
::1		localhost ip6-localhost ip6-loopback
EOF
cat > /etc/os-release <<'EOF'
PRETTY_NAME="Lumo OS 1.0 (Aurora)"
NAME="Lumo OS"
VERSION="1.0 (Aurora)"
VERSION_ID="1.0"
VERSION_CODENAME=aurora
ID=lumo
ID_LIKE=debian
HOME_URL="https://github.com/salom600/lumo-os"
SUPPORT_URL="https://github.com/salom600/lumo-os"
BUG_REPORT_URL="https://github.com/salom600/lumo-os/issues"
DEBIAN_VERSION="13.0"
EOF
cat > /etc/issue <<'EOF'
Lumo OS 1.0 (Aurora) \n \l

EOF

echo "[lumo] default keyboard"
cat > /etc/default/keyboard <<'EOF'
# KEYBOARD CONFIGURATION (edit via Settings > Keyboard)
XKBMODEL="pc105"
XKBLAYOUT="us"
XKBVARIANT=""
XKBOPTIONS=""
BACKSPACE="guess"
EOF

echo "[lumo] enabling services"
systemctl enable NetworkManager.service >/dev/null 2>&1 || true
systemctl enable bluetooth.service >/dev/null 2>&1 || true
systemctl enable zramswap.service >/dev/null 2>&1 || true
systemctl enable cups.service >/dev/null 2>&1 || true
systemctl enable ssh.service >/dev/null 2>&1 || true
# display manager: make SDDM the greeter
ln -sf /usr/lib/systemd/system/sddm.service /etc/systemd/system/display-manager.service
# live bootstrap service ships disabled-by-default trigger file? It is enabled via ConditionPathExists guard:
systemctl enable lumo-live-setup.service >/dev/null 2>&1 || true
systemctl enable lumo-test-report.service >/dev/null 2>&1 || true

echo "[lumo] initramfs (adds live-boot hooks)"
update-initramfs -u -k all

echo "[lumo] resetting machine-id (regenerated on boot)"
rm -f /etc/machine-id /var/lib/dbus/machine-id
touch /etc/machine-id

echo "[lumo] package manifest"
dpkg-query -W -f='${Package}\t${Version}\n' | sort > /var/lib/lumo/package-manifest.txt

echo "[lumo] cleaning apt caches"
apt-get clean
rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/* /var/log/*
echo "[lumo] chroot setup complete"
