# D110M qualification status

Validated 2026-11-12 on D110_M-I916162607: model 2320, hardware 4.01, firmware 4.31, 96-dot head, 203 dpi. Negotiated status revision 3.01 selects NiimBlue's D110M_V4 task; firmware version is not protocol version. The loaded stock roll is T12*40-70WHITE, 12×40 mm gap labels. Landscape source images are 320×96 pixels; left rotation produces 320 rows across a 96-dot head.

Classic address: `08:85:2D:07:26:16`; SDP confirmed SPP channel 1. BLE address: `C8:85:2D:16:26:07`. Classic pairing and repeated connections work. BLE advertisements are visible through BlueZ D-Bus, but BLE connections failed locally and are not qualified.

## Run it

Disconnect the printer in the phone app before connecting from Linux. Pair through BlueZ/Blueman once. From this workspace:

```bash
python3 scripts/niimblue-classic.py --address 08:85:2D:07:26:16 --channel 1 info

# Physical print: one 12×40 mm label, gap stock, density 3.
python3 scripts/niimblue-classic.py --address 08:85:2D:07:26:16 --channel 1 \
  --deadline 45 print fixtures/calibration-12x40.png -o left -q 3 -l 1 -n 1
```

Use `-n 2` for two copies, or provide both `fixtures/calibration-12x40.png` and `fixtures/calibration-second.png` for two different pages. Increase the bridge deadline for longer jobs. Add `-d` for protocol diagnostics. The task is detected from the printer; do not force the older D110 task.

The bridge uses a regular-user RFCOMM socket and PTY to reuse the existing serial CLI. No privileged `/dev/rfcomm` binding is needed. A per-address file lock prevents concurrent bridge connections in this workspace. The Node code also rejects concurrent jobs within one process. These locks do not coordinate unrelated apps or other installations.

## Preserved implementation

Upstream `MultiMote/niimblue-node` is pinned to `e7340dfad69b6aab1c05d2589ca012a7c0ed6313` (1.4.1), with NiimBlueLib **0.47.0-node**. The separate library research checkout is 0.49.1; its tests are separate evidence.

The local checkout already has these patches applied. To reconstruct in a fresh checkout at the pinned commit:

```bash
git apply /home/jtd/NiimbotD110M-IPP/patches/niimblue-node-bluez.patch
git apply /home/jtd/NiimbotD110M-IPP/patches/niimblue-node-hardening.patch
npm ci
npm run build
```

Place the reconstructed checkout at `research/niimblue-node` for the bridge and tests. The BlueZ patch adds pinned `dbus-next`; `scripts/niimblue-linux` selects the Noble D-Bus binding for BLE experiments. The working Classic path does not use that binding.

The hardening patch adds an overall deadline of 30 seconds per requested label, serialized completion polling for D110M_V4, cancellation hooks, quantity bounds, and disconnect-on-failure. Completion requires the printed-page count and a successful PrintEnd exchange. A separate bridge watchdog terminates an unresponsive CLI. Timeout, cancellation, or link loss can leave physical completion unknown: never automatically retry. Disconnecting cannot guarantee that the printer stops buffered output. The CLI cleanup preserves the primary printer error rather than closing an already-closed serial port again.

## Evidence

| Check | Result | Local evidence |
| --- | --- | --- |
| Identity and negotiation | Model 2320, hardware 4.01, firmware 4.31, revision 3.01 | `artifacts/metadata/classic-probe.log`, `classic-cli-info.log` |
| Official app reference | User printed LINUX TEST 4.31 and reported normal output | `artifacts/runtime/reference-print.btsnoop` |
| Capture decoding | 330 checksum-valid frames; reconstructed all 320 raster rows from 114 row packets, including section pixel counts | `reference-frames.json`, `reference-raster.png` under `artifacts/runtime/` |
| Single Linux label | Page count 1 and PrintEnd acknowledgement; user confirmed readable text, alignment and normal feed | `artifacts/metadata/linux-first-print.log` |
| Two copies | Page count 2 and PrintEnd acknowledgement | `artifacts/metadata/linux-two-copies.log` |
| Two different pages | Page count 2 and PrintEnd acknowledgement | `artifacts/metadata/linux-two-pages.log` |
| Lid open | PrintStart rejected: error 1 CoverOpen; exit 1, no raster sent | `artifacts/metadata/linux-lid-open.log` |
| Roll absent, lid closed | PrintStart rejected: error 20 WriteRfidFail; exit 1, no raster sent, clean disconnect | `artifacts/metadata/linux-no-media.log` |
| Offline regression tests | 7 tests passed: page-count completion, serialized polling, stalled responses, concurrency, transport failure, cancellation, frame buffering/checksum validation | `artifacts/metadata/local-tests.log` |

Five Linux labels were produced across three successful jobs: four calibration labels and one SECOND PAGE. The user confirmed the initial calibration's appearance and noted the four calibration labels. Batch completion is established by the protocol logs; a separate visual assessment of every batch label was not recorded. Percentage fields reached 100 while page count was still zero, confirming why page count is the completion gate.

The lid-open test exposed a redundant-disconnect exception after the correct CoverOpen error. That cleanup was fixed, rebuilt, and exercised successfully by the subsequent empty-roll test. The lid-open log preserves the original failure, including that extra exception.

Run offline checks from the workspace with `node --test tests/*.test.cjs` after building the patched CLI. Python scripts passed syntax compilation. Both patch applicability and the final TypeScript build were checked.

`scripts/decode_capture.py` decodes the saved Android H4 btsnoop trace. Its L2CAP CIDs and RFCOMM DLCI are selectors for this session, not a general Bluetooth discovery decoder. The reference raster establishes row encoding and geometry; it is not a pixel-identical comparison to the different Linux calibration artwork. Flutter AOT/native compression was not required for this unit's validated protocol path.

## State and remaining work

The phone's original `persist.bluetooth.btsnooplogmode` value was empty; it was saved, restored, and verified after capture. Phone Bluetooth was re-enabled. The app and app data remain intact; no firmware update was performed. User was asked to replace the roll after the empty-roll test.

The laptop's repeated suspends were caused by the phone triggering its magnetic lid sensor. Moving it restored an open reading; power settings were not changed.

Physical disconnect-during-print and cancellation-during-print tests remain unperformed; these paths have synthetic regression coverage. BLE, alternate stock/dimensions, unattended service operation, and normal desktop printing via IPP/PAPPL or CUPS are not qualified. The implemented deliverable is the bounded Classic CLI printing path, not yet a desktop printer queue. Keep the original plan's desktop integration milestone separate from these results.
