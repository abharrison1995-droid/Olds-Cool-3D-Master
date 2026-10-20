# Additional independent reader setup

Root installed a QA-only reader in the existing developer `.venv`:

```text
.venv\Scripts\python.exe -m pip install --index-url https://pypi.org/simple --disable-pip-version-check --no-deps --quiet --report work/v1/trimesh-install.json trimesh==5.1.1
exit 0
```

The installed version is 5.1.1; downloaded wheel SHA-256 is
`c5be85a3e31e9ff749f9b0aecc204e37a2cf7cca4e92cd066bb5f3d3c1127765`.
This does not change application requirements or the isolated packaged-build
environment. It is an extra reader for final generated OBJ/GLB artifacts,
separate from the application's validators.

The [official loader documentation](https://trimesh.org/trimesh.exchange.load.html)
describes `load_scene` and its default prohibition on remote fetching.
Artifact-reader checks will explicitly disable remote fetching. Installation
alone is not export, visual, native-display or target-platform acceptance;
actual artifact identities and executed results remain to be recorded.
