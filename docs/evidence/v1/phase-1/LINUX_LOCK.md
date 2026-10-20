# Linux dependency additions

The Phase 1 review identified that `build_linux.sh` installs only the Linux
lock, so adding dependencies to runtime requirements alone was insufficient.
The existing Linux pins were preserved and the provider/secure-backend closure
was added to `requirements-lock-linux.txt`.

Resolution was performed on Windows with pip 25.0.1, **not by executing a
native Mint environment**. The resolver's vendored packaging marker environment
was explicitly set to Linux/posix/x86-64/CPython 3.13.5 before importing pip's
CLI. The effective pip arguments were:

```
install --dry-run --ignore-installed --only-binary=:all:
--platform manylinux_2_34_x86_64 --platform manylinux_2_28_x86_64
--platform manylinux2014_x86_64 --platform manylinux_2_17_x86_64
--python-version 3.13 --report work/v1/linux-additions-report.json
-c requirements-lock-linux.txt
httpx==0.28.1 keyring==25.7.0 SecretStorage==3.5.0
```

All selected distributions had compatible target wheels. `linux-lock-resolution.json`
records the resulting 17 additions, wheel SHA-256 identities and updated lock
identity. No Linux modules were installed into the Windows source environment.

This closes the known missing lock entries for implementation preparation; it
does not certify the complete Linux frozen payload, native installation, D-Bus
service availability, unlocked Secret Service, or Mint target behavior. Those
remain actual Phase 10 gates. Freeze hooks must explicitly include the approved
platform backend and HTTP CA bundle; source dependency resolution alone cannot
prove frozen dynamic imports work.
