"""Lumo Store - drivers detection helpers (real hardware probing)."""
import os
import re
import subprocess


def _run(cmd, timeout=10):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except Exception:
        return ""


def gpu_info():
    """Return list of (pci_id, vendor, model) for VGA/3D controllers."""
    out = _run(["lspci", "-nn"])
    gpus = []
    for line in out.splitlines():
        if re.search(r"VGA compatible controller|3D controller|Display controller", line):
            m = re.search(r"\[(10de|8086|1002):\w{4}\]", line)
            vendor = {"10de": "nvidia", "8086": "intel", "1002": "amd"}.get(
                m.group(1) if m else "", "unknown")
            model = line.split(":", 2)[-1].strip()
            gpus.append((m.group(1) if m else "", vendor, model))
    return gpus


def missing_firmware():
    """Kernel-reported missing firmware from dmesg/journal."""
    text = _run(["journalctl", "-kb", "--no-pager", "-g", "firmware"], timeout=15)
    if not text:
        text = _run(["dmesg"])
    missing = set()
    for m in re.finditer(r"failed to load ([\w\-/.]+\.bin|firmware[^\s\"]]*)", text):
        missing.add(m.group(1))
    for m in re.finditer(r"firmware file ['\"]?([\w\-/.]+)", text):
        missing.add(m.group(1))
    return sorted(missing)


def recommendations():
    """Return list of dicts: {title, desc, packages, present}."""
    recs = []
    for pci, vendor, model in gpu_info():
        if vendor == "nvidia":
            recs.append({
                "title": "NVIDIA proprietary driver",
                "desc": f"{model} detected. Installs nvidia-driver with kernel module "
                        "and GL/Vulkan libraries (non-free).",
                "packages": ["nvidia-driver", "firmware-misc-nonfree"],
                "present": False,
            })
        elif vendor == "amd":
            recs.append({
                "title": "AMD graphics (already open source)",
                "desc": f"{model} is supported by the open-source AMDGPU/Mesa stack, "
                        "which is preinstalled.",
                "packages": [],
                "present": True,
            })
        elif vendor == "intel":
            recs.append({
                "title": "Intel graphics (already open source)",
                "desc": f"{model} is supported by the open-source Intel/Mesa stack, "
                        "which is preinstalled.",
                "packages": [],
                "present": True,
            })

    for fw in missing_firmware():
        pkg = None
        if "iwlwifi" in fw or fw.startswith("iwl"):
            pkg = "firmware-iwlwifi"
        elif "rtl" in fw or "realtek" in fw:
            pkg = "firmware-realtek"
        elif "ath" in fw:
            pkg = "firmware-atheros"
        elif "brcm" in fw:
            pkg = "firmware-brcm80211"
        elif "sof" in fw:
            pkg = "firmware-sof-signed"
        elif "amdgpu" in fw or "radeon" in fw:
            pkg = "firmware-amd-graphics"
        elif "nvidia" in fw:
            pkg = "firmware-misc-nonfree"
        if pkg:
            recs.append({
                "title": f"Missing firmware: {os.path.basename(fw)}",
                "desc": "The kernel reported missing firmware. Installing this package "
                        "enables the affected device (Wi-Fi, audio or GPU).",
                "packages": [pkg],
                "present": False,
            })

    if not recs:
        recs.append({
            "title": "All good",
            "desc": "No missing firmware or proprietary driver needs were detected "
                    "on this system. Open-source drivers cover your hardware.",
            "packages": [],
            "present": True,
        })
    return recs


GAME_TOOLS = [
    {
        "id": "steam-installer",
        "name": "Steam",
        "desc": "Valve's game platform (contrib). Enables Proton for Windows games.",
    },
    {
        "id": "wine",
        "name": "Wine",
        "desc": "Run Windows applications and games directly.",
    },
    {
        "id": "gamemode",
        "name": "GameMode",
        "desc": "On-demand CPU/IO performance profiles (integrated with Lumo Game Mode).",
    },
    {
        "id": "mangohud",
        "name": "MangoHud",
        "desc": "In-game performance overlay (FPS, CPU/GPU usage).",
    },
    {
        "id": "joystick",
        "name": "Joystick tools (jstest)",
        "desc": "Test and calibrate game controllers from the terminal.",
    },
    {
        "id": "linuxconsoletools",
        "name": "Linux console joystick utils",
        "desc": "inputattach and utilities for legacy game controllers.",
    },
]
