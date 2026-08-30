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

  # make shell scripts executable
  find "$stage/usr" "$stage/lib" "$stage/etc" -type f \
    \( -path '*/bin/*' -o -path '*/sbin/*' -o -name '*.sh' \) \
    -exec chmod 0755 {} \; 2>/dev/null || true

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
