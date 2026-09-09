# Linux reference acceptance machine (verified present)

Captured 2026-09-09 on the machine this implementation runs on. This IS the
mandatory Linux acceptance target described in DESKTOP_RELEASE_PLAN.md, so
Linux Phase E checks are performable rather than BLOCKED.

```text
/etc/mx-version : MX-25.2_KDE_x64 Infinity May 24, 2026
/etc/os-release : Debian GNU/Linux 13 (trixie)
kernel          : 6.12.90+deb13-amd64  x86_64
desktop         : KDE Plasma / kwin 6.3.6, plasmashell 6.3.6
session         : XDG_SESSION_TYPE=wayland (wayland-0), XWayland on :0
cpu             : AMD Ryzen 7 5700U with Radeon Graphics
memory          : 30 GiB usable (32 GiB installed)
gpu             : 03:00.0 AMD/ATI Lucienne (rev c1), radeonsi/renoir, amdgpu
mesa            : 26.1.4, OpenGL max core profile 4.6, direct rendering yes
```

Windows has no machine available in this environment; every Windows-only
check is recorded as BLOCKED, never PASS.
