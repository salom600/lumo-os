#!/usr/bin/env bash
# Build all Lumo .deb packages into build/debs/
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$HERE/build/debs"
WORK="$HERE/build/deb-staging"
rm -rf "$OUT" "$WORK"; mkdir -p "$OUT" "$WORK"

for pkg in "$HERE"/packages/*/; do
  name="$(basename "$pkg")"
  [ -f "$pkg/debian/control" ] || { echo "skip $name (no debian/control)"; continue; }
  version="$(dpkg-parsechangelog -l "$pkg/debian/changelog" -S Version)"
  echo "==> Building $name $version"

  stage="$WORK/$name"
  rm -rf "$stage"; mkdir -p "$stage"

  # copy the FHS payload (everything except debian/) - plain tar, no tricks
  (cd "$pkg" && tar cf - --exclude=./debian --exclude=__pycache__ --exclude=.pyc .) \
    | (cd "$stage" && tar xf -)

  # packaging metadata
  mkdir -p "$stage/DEBIAN"
  cp "$pkg/debian/control" "$stage/DEBIAN/control"
  sed -i "s/^Version: .*/Version: ${version}/" "$stage/DEBIAN/control"
  if [ -f "$pkg/debian/conffiles" ]; then
    cp "$pkg/debian/conffiles" "$stage/DEBIAN/conffiles"
  fi
  if [ -f "$pkg/debian/postinst" ]; then
    cp "$pkg/debian/postinst" "$stage/DEBIAN/postinst"
    chmod 0755 "$stage/DEBIAN/postinst"
  fi

  # make executables executable:
  #  - everything in FHS bin/sbin dirs and /usr/libexec
  #  - anything with a shebang line (session scripts, helpers, hooks)
  find "$stage" -type f \
    \( -path '*/bin/*' -o -path '*/sbin/*' -o -path '*/libexec/*' \) \
    -exec chmod 0755 {} \; 2>/dev/null || true
  while IFS= read -r f; do
    head -c 2 "$f" | grep -q '#!' && chmod 0755 "$f"
  done < <(find "$stage" -path "$stage/DEBIAN" -prune -o -type f -print 2>/dev/null)

  # guard: never ship an empty package again
  payload="$(find "$stage" -path "$stage/DEBIAN" -prune -o -type f -print | wc -l)"
  if [ "$payload" -eq 0 ]; then
    echo "ERROR: $name staging produced 0 payload files - aborting"
    exit 1
  fi
  echo "    payload files: $payload"

  dpkg-deb --root-owner-group --build "$stage" "$OUT/${name}_${version}_all.deb" >/dev/null
done

echo "==> Built debs:"
ls -la "$OUT"
