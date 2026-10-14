# Upstream and provenance

syslinuxos-anonimo is written from scratch for SysLinuxOS (2026). It does not
contain code from ParrotSec AnonSurf (https://github.com/ParrotSec/anonsurf),
which inspired its purpose.

## Default snowflake bridge lines

`packaging/snowflake-bridges` (installed as
`/usr/share/syslinuxos-anonimo/snowflake-bridges`) contains the default
snowflake bridge lines of Tor Browser:

- Repository: https://gitlab.com/torproject/tor-browser-build (mirror of
  https://gitlab.torproject.org/tpo/applications/tor-browser-build)
- File: `projects/tor-expert-bundle/pt_config.json`
- Commit: `01d3e9d35aabbc52bfad4e33686f1c83edfa3ce3` (2026-04-09)

Conversion for Debian snowflake-client 2.5.1, which accepts `url`, `front`,
`ice`, `fingerprint` and `utls-imitate` but not `fronts`:
`fronts=app.datapacket.com,www.datapacket.com` → `front=app.datapacket.com`.
Update these lines when Tor Browser changes them.
