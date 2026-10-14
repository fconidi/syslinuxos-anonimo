# Changelog

All notable changes to SysLinuxOS Anonimo. The version is `YYYY.M.N`.

## 2026.10.1 - 2026-10-14

First release.

- All TCP connections and DNS queries of the computer go through Tor; the rest of the
  outgoing traffic is blocked, except the local network (option, on by default) and DHCP.
- Its own nftables table (`inet anonimo`) and its own Tor instance
  (`syslinuxos-anonimo-tor.service`): ufw, Docker, libvirt, `/etc/tor/torrc`, `resolv.conf`
  and NetworkManager are not touched.
- Fails closed: if Tor stops, traffic stays blocked. The table is loaded again when
  `nftables.service` is reloaded.
- Qt window and notification-area icon (grey off, yellow connecting, green protected, red error),
  `anonimo` command (`start`, `stop`, `status --check`, `identity`, `settings`), man page.
- Settings: direct local network, obfs4 and snowflake bridges, start at boot, closing network
  applications and cleaning caches with BleachBit.
- Interface in English, Italian, French, German and Spanish.
- `obfs4proxy` is a hard dependency, so obfs4 bridges work right after installation.
- Checked with 202 automated tests, a 40-check run in a SysLinuxOS Live VM with packet capture
  analysis, and manual tests on SysLinuxOS MATE, GNOME and GNOME Classic (obfs4 bridges, reboot with start at boot, tray). See [VALIDATION.md](VALIDATION.md).
