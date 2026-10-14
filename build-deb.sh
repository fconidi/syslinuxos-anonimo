#!/bin/bash
# Build without root, network access or host installation.
set -euo pipefail
umask 022

PKG_NAME="syslinuxos-anonimo"
WORKDIR="$(cd "$(dirname "$0")" && pwd)"
PKG_VERSION="$(cat "$WORKDIR/source/VERSION")"
OUTPUT="$WORKDIR/${PKG_NAME}_${PKG_VERSION}_all.deb"
LIB="usr/lib/$PKG_NAME"

for tool in python3 dpkg-deb desktop-file-validate; do
    command -v "$tool" >/dev/null || { echo "Missing build dependency: $tool" >&2; exit 1; }
done
cd "$WORKDIR"
mkdir -p "$WORKDIR/staging"
PACKAGE_DIR="$(mktemp -d "$WORKDIR/staging/package.XXXXXX")"
chmod 755 "$PACKAGE_DIR"
trap 'rm -rf -- "$PACKAGE_DIR"' EXIT
mkdir -p "$PACKAGE_DIR/DEBIAN" "$PACKAGE_DIR/$LIB" "$PACKAGE_DIR/usr/share/doc/$PKG_NAME" \
    "$PACKAGE_DIR/usr/share/$PKG_NAME/icons" "$PACKAGE_DIR/usr/share/man/man1"
for file in "$WORKDIR/source/"*.py "$WORKDIR/source/VERSION"; do
    install -m644 "$file" "$PACKAGE_DIR/$LIB/"
done
install -m755 "$WORKDIR/source/anonimo-helper" "$WORKDIR/source/anonimo-watch" "$PACKAGE_DIR/$LIB/"
install -Dm755 "$WORKDIR/packaging/anonimo" "$PACKAGE_DIR/usr/bin/anonimo"
install -Dm755 "$WORKDIR/packaging/$PKG_NAME" "$PACKAGE_DIR/usr/bin/$PKG_NAME"
for unit in tor watch boot; do
    install -Dm644 "$WORKDIR/packaging/$PKG_NAME-$unit.service" \
        "$PACKAGE_DIR/usr/lib/systemd/system/$PKG_NAME-$unit.service"
done
install -Dm644 "$WORKDIR/packaging/nftables-syslinuxos-anonimo.conf" \
    "$PACKAGE_DIR/usr/lib/systemd/system/nftables.service.d/$PKG_NAME.conf"
install -Dm644 "$WORKDIR/packaging/com.syslinuxos.anonimo.helper.policy" \
    "$PACKAGE_DIR/usr/share/polkit-1/actions/com.syslinuxos.anonimo.helper.policy"
install -Dm644 "$WORKDIR/packaging/$PKG_NAME.desktop" "$PACKAGE_DIR/usr/share/applications/$PKG_NAME.desktop"
install -Dm644 "$WORKDIR/packaging/$PKG_NAME.menu" "$PACKAGE_DIR/etc/xdg/menus/applications-merged/$PKG_NAME.menu"
echo "/etc/xdg/menus/applications-merged/$PKG_NAME.menu" > "$PACKAGE_DIR/DEBIAN/conffiles"
install -Dm644 "$WORKDIR/packaging/$PKG_NAME.svg" "$PACKAGE_DIR/usr/share/icons/hicolor/scalable/apps/$PKG_NAME.svg"
install -m644 "$WORKDIR/packaging/icons/"anonimo-*.svg "$PACKAGE_DIR/usr/share/$PKG_NAME/icons/"
install -m644 "$WORKDIR/packaging/snowflake-bridges" "$PACKAGE_DIR/usr/share/$PKG_NAME/snowflake-bridges"
install -m644 "$WORKDIR/README.md" "$WORKDIR/UPSTREAM.md" "$WORKDIR/packaging/copyright" \
    "$PACKAGE_DIR/usr/share/doc/$PKG_NAME/"
gzip -9 -n -c "$WORKDIR/packaging/changelog" > "$PACKAGE_DIR/usr/share/doc/$PKG_NAME/changelog.gz"
gzip -9 -n -c "$WORKDIR/packaging/anonimo.1" > "$PACKAGE_DIR/usr/share/man/man1/anonimo.1.gz"
for script in postinst prerm postrm; do
    install -m755 "$WORKDIR/packaging/$script" "$PACKAGE_DIR/DEBIAN/$script"
done
desktop-file-validate "$PACKAGE_DIR/usr/share/applications/$PKG_NAME.desktop"
python3 - "$PACKAGE_DIR" <<'PY'
from pathlib import Path
import sys
import xml.etree.ElementTree as ET
root = Path(sys.argv[1])
for pattern in ['usr/share/polkit-1/actions/*.policy', 'etc/xdg/menus/applications-merged/*.menu',
                'usr/share/icons/hicolor/scalable/apps/*.svg', 'usr/share/syslinuxos-anonimo/icons/*.svg']:
    for path in root.glob(pattern):
        ET.parse(path)
PY
INSTALLED_SIZE="$(du -sk --exclude=DEBIAN "$PACKAGE_DIR" | cut -f1)"
cat > "$PACKAGE_DIR/DEBIAN/control" <<EOF
Package: $PKG_NAME
Version: $PKG_VERSION
Section: net
Priority: optional
Architecture: all
Maintainer: Franco Conidi <fconidi@gmail.com>
Depends: python3 (>= 3.11), python3-pyqt5 (>= 5.15), libqt5svg5, tor, obfs4proxy, nftables, pkexec, adduser
Recommends: snowflake-client, bleachbit, mate-polkit | polkit-1-auth-agent
Homepage: https://syslinuxos.com/
Installed-Size: $INSTALLED_SIZE
Description: route TCP and DNS traffic of the computer through Tor
 SysLinuxOS Anonimo sends every TCP connection and every DNS query of the
 computer through Tor. Everything else leaving the computer is blocked, except
 traffic to the local network (when the direct local network option is on, as
 by default) and DHCP. Services of this computer cannot answer hosts outside
 the local network, and connections to the Internet already open when it
 switches on are cut.
 It adds its own nftables table and its own Tor instance without touching ufw,
 resolv.conf or /etc/tor/torrc. Tray icon, the anonimo command, obfs4 and
 snowflake bridges, optional start at boot.
EOF
dpkg-deb --root-owner-group --build "$PACKAGE_DIR" "$OUTPUT"
echo "Package ready: $OUTPUT"
