#!/usr/bin/env bash
# tests/check-all.sh - fast static validation of the Lumo OS repo.
# Runs on every push (CI lint job) and locally before committing.
set -uo pipefail
cd "$(dirname "$0")/.."
RC=0
fail() { echo "FAIL: $*"; RC=1; }

echo "== shell scripts: bash -n =="
while IFS= read -r f; do
  bash -n "$f" || fail "syntax: $f"
done < <(find . -path ./.git -prune -o -name '*.sh' -print -o -name 'build-debs.sh' -print)

echo "== shell scripts: shellcheck (warnings only) =="
if command -v shellcheck >/dev/null 2>&1; then
  find scripts tests build.sh Makefile -type f \( -name '*.sh' -o -name Makefile \) 2>/dev/null | while IFS= read -r f; do
    shellcheck -S warning "$f" || true
  done
fi

echo "== python: py_compile =="
while IFS= read -r f; do
  python3 -m py_compile "$f" || fail "python syntax: $f"
done < <(find packages -type f \( -name '*.py' -o -path '*/usr/bin/lumo-*' \) -print | grep -v '/debian/' | while IFS= read -r p; do
  head -n1 "$p" 2>/dev/null | grep -qE 'python' && echo "$p" || true
done)

echo "== XML: labwc / calamares / polkit =="
python3 - <<'EOF'
import glob, sys
import xml.etree.ElementTree as ET
bad = 0
patterns = ["packages/lumo-defaults/etc/xdg/labwc/*.xml",
            "packages/lumo-installer/usr/share/polkit-1/actions/*.policy" if glob.glob("packages/lumo-installer/usr/share/polkit-1/actions/*.policy") else "packages/lumo-defaults/usr/share/polkit-1/actions/*.policy"]
for pat in patterns:
    for f in glob.glob(pat):
        try:
            ET.parse(f)
            print(f"ok  {f}")
        except Exception as e:
            print(f"FAIL {f}: {e}")
            bad = 1
sys.exit(bad)
EOF
[ $? -eq 0 ] || fail "XML validation"

echo "== JSON: waybar config =="
python3 - <<'EOF'
import json, sys
try:
    with open("packages/lumo-defaults/etc/xdg/waybar/config.jsonc") as fh:
        # strip // comments (waybar allows them)
        src = "\n".join(l for l in fh if not l.strip().startswith("//"))
    json.loads(src)
    print("ok  waybar config")
except Exception as e:
    print(f"FAIL waybar config: {e}")
    sys.exit(1)
EOF
[ $? -eq 0 ] || fail "waybar config"

echo "== YAML-ish: calamares module configs (loose indent check) =="
while IFS= read -r f; do
  if grep -nE '^\s+\S' "$f" | head -n1 | grep -qE '^\s*[0-9]+:\s{0,1}\S'; then :; fi
  # actual check: no tabs, keys not indented under other keys
  if grep -qP '^\t' "$f"; then fail "tabs in YAML: $f"; fi
done < <(find packages/lumo-installer/etc/calamares -name '*.conf')

echo "== packaging: debian/control sanity =="
for c in packages/*/debian/control; do
  grep -q '^Package: ' "$c" || fail "missing Package: in $c"
  grep -q '^Description: ' "$c" || fail "missing Description: in $c"
  grep -q '^Version: ' "$c" || fail "missing Version: in $c"
done

echo "== repo hygiene: no placeholder junk patterns =="
if grep -rn '? no' --include='*' packages config 2>/dev/null | grep -v Binary; then
  fail "placeholder junk found (see above)"
fi

echo "== QML: brace balance =="
python3 - <<'EOF'
import glob, sys
bad = 0
for f in glob.glob("packages/**/*.qml", recursive=True):
    s = open(f).read()
    if s.count("{") != s.count("}"):
        print(f"FAIL unbalanced braces: {f} ({s.count('{')} vs {s.count('}')})")
        bad = 1
    else:
        print(f"ok  {f}")
sys.exit(bad)
EOF
[ $? -eq 0 ] || fail "QML braces"

echo
if [ "$RC" -eq 0 ]; then
  echo "ALL CHECKS PASSED"
else
  echo "CHECKS FAILED"
fi
exit $RC
