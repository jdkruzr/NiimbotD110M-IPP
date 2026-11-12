# Niimbot D110M Linux research

Linux Bluetooth Classic printing is working on this D110M (hardware 4.01, firmware 4.31), using the community NiimBlue encoder with a userspace RFCOMM bridge and bounded job handling. Single labels, two copies, and two distinct pages completed; lid-open and missing-roll jobs were rejected correctly.

See [qualification results and usage](docs/qualification-status.md) for the tested commands, reproducible patches, and remaining limitations. This is a working CLI path; desktop IPP/CUPS integration is still a separate milestone.

See [findings and implementation plan](docs/linux-driver-plan.md) for evidence, limitations, commands, and acceptance criteria.

Local research captured on 2026-11-12:

- `artifacts/apk/`: all three APKs pulled from the connected phone, NIIMBOT 6.7.0.
- `artifacts/metadata/`: package details, SHA-256 hashes, extracted D110_M definition, and build/test logs.
- `decompiled/jadx/`: decoded resources and exposed Java wrapper.
- `decompiled/cfr/`: independent decompilation of the exposed Java wrapper, via dex2jar.
- `artifacts/runtime/dex-pass2/`: six recovered application DEX files plus one tiny generated DEX, with verified original checksums and a manifest.
- `decompiled/runtime-jadx/`: recovered application sources, including the printer SDK; 207 decompiler errors remain.
- `decompiled/runtime-cfr/`: selected printer SDK classes cross-checked with CFR.
- `scripts/dump_runtime_dex.py`: reproducible, read-only extraction through rooted ADB.
- `artifacts/native/`: selected ARM64 libraries, including the Flutter AOT library.
- `research/`: pinned upstream checkouts; `niimblue-node` is built locally.

The APK protects its implementation with SecNeo and includes Flutter AOT code. Initial static decompilation exposed only the wrapper. After Shell root access was enabled in KernelSU, read-only extraction from the already-running app recovered 61,312,404 bytes of application DEX containing 45,216 class definitions. The printer SDK is now readable. See [runtime recovery findings](docs/runtime-recovery.md); native and Flutter AOT code remain separate analysis targets.

Five Linux labels were printed during qualification: four calibration labels and one SECOND PAGE label. The user confirmed the first label looked correct. The installed phone app and its data were left intact, and the temporary Bluetooth logging property was restored. No firmware was flashed.

Local desktop printing is now available as `Niimbot_D110M`. See [IPP integration development status](docs/ipp-integration.md) for setup, packaging, validation and remaining qualification work.

For a fresh clone, install `libpappl-dev`, `libcups2-dev`, Node.js 22+, npm,
Python 3, and Git, then run `./scripts/bootstrap`. This reconstructs the
pinned community dependency and applies the preserved patches before building.
Run `node --test tests/*.test.cjs` for offline regression checks.

Extracted APKs, decompiled vendor code, packet captures, downloaded tooling,
and build artifacts are deliberately excluded from Git. They remain local;
the repository contains the implementation, fixtures, reproducible patches,
and research findings.

For a read-only lid/paper/RFID refresh, run `./scripts/niimbot-status`.
Queue setup applies the CUPS 2.x PNG copy workaround; `lp -n 2` is hardware-tested.
