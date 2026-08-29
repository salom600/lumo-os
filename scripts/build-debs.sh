#!/usr/bin/env bash
# Build all Lumo .deb packages into build/debs/
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$HERE/build/debs"
rm -rf "$OUT"; mkdir -p "$OUT"

for pkg in "$HERE"/packages/*/; do
  name="$(basename "$pkg")"
  [ -f "$pkg/debian/control" ] || { echo "skip $name (no debian/control)"; continue; }
  version="$(dpkg-parsechangelog -l "$pkg/debian/changelog" -S Version)"
  echo "==> Building $name $version"
  stage="$(mktemp -d)"
  # copy FHS tree (skip debian dir, copy its control/conffiles/postinst into DEBIAN/)
  (cd "$pkg" && find . -path ./debian -prune -o -type f -print -o -type d -print | while read -r p; do
      [[ "$p" == "./debian" || "$p" == ./debian/* ]] && continue
      mkdir -p "$stage$p"
  done)
  (cd "$pkg" && find . -path ./debian -prune -o -type f -print | while read -r p; do
      [[ "$p" == "./debian" || "$p" == ./debian/* ]] && continue
      cp "$p" "$stage$p"
  done)
  mkdir -p "$stage/DEBIAN"
  # make shell scripts executable
  find "$stage" -type f \( -path '*/bin/*' -o -path '*/sbin/*' -o -name '*.sh' \) -exec chmod 0755 {} \; 2>/dev/null || true
  cp "$pkg/debian/control" "$stage/DEBIAN/control"
  sed -i "s/^Version: .*/Version: ${version}/" "$stage/DEBIAN/control"
  [ -f "$pkg/debian/conffiles" ] && cp "$pkg/debian/conffiles" "$stage/DEBIAN/conffiles"
  if [ -f "$pkg/debian/postinst" ]; then
    cp "$pkg/debian/postinst" "$stage/DEBIAN/postinst"; chmod 0755 "$stage/DEBIAN/postinst"
  fi
  [ -f "$pkg/debian/triggers" ] && cp "$pkg/debian/triggers" "$stage/DEBIAN/triggers"
  dpkg-deb --root-owner-group --build "$stage" "$OUT/${name}_${version}_all.deb" >/dev/null
  rm -rf "$stage"
done

echo "==> Built debs:"
ls -la "$OUT"
