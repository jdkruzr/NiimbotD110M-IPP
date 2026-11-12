#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
make -C ipp
stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT
base="$stage/usr/lib/niimbot"
mkdir -p "$base/ipp" "$base/scripts" "$base/research/niimblue-node" "$stage/DEBIAN"
cp ipp/niimbot-ipp ipp/worker.cjs ipp/supervise.py ipp/status.py ipp/refresh.py "$base/ipp/"
cp scripts/niimbot-status scripts/fix-cups-image-copies.py scripts/process_guard.py scripts/niimbot-setup scripts/niimblue-classic.py "$base/scripts/"
cp -a research/niimblue-node/dist research/niimblue-node/node_modules "$base/research/niimblue-node/"
cat > "$stage/DEBIAN/control" <<CONTROL
Package: niimbot-ipp
Version: 0.1.0~dev4
Architecture: $(dpkg --print-architecture)
Maintainer: Local Niimbot Development <nobody@localhost>
Depends: libpappl1t64, libcups2t64, nodejs (>= 22), python3, curl, cups-ipp-utils, cups-client, cups-filters
Description: Experimental local Niimbot D110M printer application
 Local IPP adapter for 12x40 mm gap labels. Development package.
CONTROL
mkdir -p artifacts/packages
dpkg-deb --root-owner-group --build "$stage" "artifacts/packages/niimbot-ipp_0.1.0~dev4_$(dpkg --print-architecture).deb"
