# Downstream Codex recipe-only prototype

This directory preserves the independently reviewed source and lockfile
patches for a downstream Codex CLI prototype. It is not an official Codex
release, does not include a compiled executable, and does not establish that a
modified executable is supported for subscription authentication or
distribution.

## Pinned source and patches

- Upstream: [openai/codex](https://github.com/openai/codex)
- Upstream commit: `740e5af33c71225640e0c1c1555c514c2c93ab74`
- Upstream version: `0.162.0-alpha.17.2`
- Upstream license and notice: [`UPSTREAM-LICENSE.txt`](UPSTREAM-LICENSE.txt),
  [`UPSTREAM-NOTICE.txt`](UPSTREAM-NOTICE.txt)
- Reviewed recipe-only patch: [`recipe-only.patch`](recipe-only.patch),
  SHA-256 `0481c3e9c2969871b2f2455dd52e6b9be6afe9f57cdec48175f0d6e0912a7e66`
- Reviewed derived lockfile patch: [`derived-lockfile.patch`](derived-lockfile.patch),
  SHA-256 `a91879cf192e40e7b0293f487300917a6702ef24fbaae80e5cdb0afb85e00ec2`
- Original `codex-rs/Cargo.lock` SHA-256:
  `1b7f27d5ec01ad9b19bfe8823557418772f851d367e8a6577544a9ab841b8d65`
- Derived `codex-rs/Cargo.lock` SHA-256:
  `49575eeb44a747925fd1acef51bff88316f728b77d7f63d989835c8623c344cb`
- Required Rust toolchain: `1.95.0`

The source patch changes 15 Rust files. The separate lockfile patch updates 161
internal workspace versions; all 1,312 external dependency records were
verified unchanged. M3.2f additions are kept in a separate downstream delta so
the reviewed patch bytes remain intact.

## Reproduction

Use the repository script `scripts/build_recipe_only_codex.py` with an already
available checkout at the exact upstream commit. It applies these pinned
patches and the separately recorded M3.2f delta, resolves dependencies only
with Cargo's locked offline mode, runs the recipe-only self-test, and writes a
platform-specific candidate executable and unapproved manifest outside the
installed Codex application. It does not fetch dependencies, touch
authentication files, or install the executable.

An emitted candidate manifest is not an approval. A production adapter must
use a separately owner-approved manifest anchored by the application host;
passing the self-test alone never approves a local build.
