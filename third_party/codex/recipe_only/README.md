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
- Combined M3.2f prototype worktree snapshot:
  [`m3.2f-prototype-snapshot.patch.gz`](m3.2f-prototype-snapshot.patch.gz),
  compressed SHA-256 `891d7dc9029dbcde2592581cca7b3c8111e227124e3352a3449e0021914aae4c`,
  uncompressed SHA-256 `c675a03d3051192bfce3b8e960cf7966b91c4eac24298fa4131d7b09a32a3ee1`
- Original `codex-rs/Cargo.lock` SHA-256:
  `1b7f27d5ec01ad9b19bfe8823557418772f851d367e8a6577544a9ab841b8d65`
- Derived `codex-rs/Cargo.lock` SHA-256:
  `49575eeb44a747925fd1acef51bff88316f728b77d7f63d989835c8623c344cb`
- Required Rust toolchain: `1.95.0`

The reviewed source patch changes 15 Rust files. The separate lockfile patch
updates 161 internal workspace versions; all 1,312 external dependency records
were verified unchanged. The M3.2f snapshot is a combined worktree diff against
the pinned upstream commit: it includes the recipe-only changes, derived lockfile
and M3.2f additions. The standalone reviewed patches remain unchanged as
provenance records. Apply either the combined snapshot or the two standalone
patches followed by a separately developed M3.2f delta; do not apply both forms
on top of each other.

## Reproduction

To restore the exact preserved prototype on another device, check out the
upstream commit above and apply the combined snapshot:

```sh
git clone https://github.com/openai/codex /tmp/codex-recipe-only
git -C /tmp/codex-recipe-only checkout 740e5af33c71225640e0c1c1555c514c2c93ab74
gzip -dc /path/to/Olds-Cool-3D-Master/third_party/codex/recipe_only/m3.2f-prototype-snapshot.patch.gz | git -C /tmp/codex-recipe-only apply --check -
gzip -dc /path/to/Olds-Cool-3D-Master/third_party/codex/recipe_only/m3.2f-prototype-snapshot.patch.gz | git -C /tmp/codex-recipe-only apply -
```

The compressed snapshot was verified by hash and its contents passed
`git apply --check` against a clean checkout at the pinned commit. Compression
preserves upstream whitespace exactly. It contains source and tests only; it
does not contain the Cargo target cache, a compiled executable, or an approved
binary manifest. The current build remains incomplete, and no candidate
self-test has passed.

An emitted candidate manifest is not an approval. A production adapter must
use a separately owner-approved manifest anchored by the application host;
passing the self-test alone never approves a local build.
