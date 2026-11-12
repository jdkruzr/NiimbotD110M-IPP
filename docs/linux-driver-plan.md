# Niimbot D110M Linux driver plan

Use the existing NiimBlue protocol implementation first. Its Node CLI builds on this Linux host and includes a D110M-specific print task. Qualifying that path on the physical printer should establish whether the remaining work is mostly packaging and desktop integration. A new protocol implementation is a fallback, supported by a separate D110M Bluetooth capture project.

This assessment is dated 2026-11-12. Subsequent implementation established working Classic SPP printing on this unit. See [current qualification results and commands](qualification-status.md); the assessment and candidate commands below preserve the initial research context, not the current test status.

Root access subsequently enabled [runtime recovery of the protected DEX payload](runtime-recovery.md). The recovered SDK independently confirms frame construction, Classic SPP transport code, and row-encoding decisions. The full model and firmware dispatch path has not yet been traced. The initial static-analysis limitations below describe what was available before that recovery.

## Initial app extraction and static decompilation

Pulled `com.gengcon.android.jccloudprinter` version **6.7.0**, version code **611022046**, from the single ADB-connected phone. Saved `base.apk`, `split_config.arm64_v8a.apk`, and `split_config.xxhdpi.apk` under `artifacts/apk/`. Package metadata and hashes are under `artifacts/metadata/`.

JADX 1.5.6 completed successfully. The APK's only exposed `classes.dex` is 21,992 bytes and contains the SecNeo loader rather than the main application. The manifest names `com.secneo.apkwrapper.AW`; `H.java` loads `DexHelper` and names the original application class. dex2jar 2.4 and CFR 0.152 independently recovered the same wrapper. These tools cannot turn protected payloads or Flutter ARM64 AOT machine code into the missing Java print implementation.

The native split includes `libapp.so` and `libflutter.so`, plus SecNeo-related libraries and `libdatajar.so`. Strings in `libapp.so` expose names such as `NiimbotSecurityPrintHelper`, `NiimbotPrinterPrintStatus`, and `connectBluetoothPrinterWithRetry`. Names establish components, not their behavior; they do not prove authentication is required for a print job. The subsequent runtime recovery required neither app replacement nor injected instrumentation.

The bundled model definition is directly readable at `decompiled/jadx/resources/assets/DevicesModule_en.json:4561`; an extracted copy is in `artifacts/metadata/d110m-model.json`.

| Setting | App asset value | Interpretation |
| --- | --- | --- |
| Model | `D110_M`, code `2320` (`0x0910`) | Distinct from D110, code 2304 |
| Resolution | `paccuracyName=203`, `paccuracy=8` | 203 dpi, approximately 8 dots/mm |
| Width settings | `widthSetStart=12`, `widthSetEnd=12` | Consistent with the community 96-dot printhead definition |
| Maximum width field | `maxPrintWidth=15` | Do not equate this with 120 printable dots; distinguish label width from printhead width |
| Default layout | Width 30, height 12, direction 90 | Start with a 30 mm long by 12 mm printable label layout |
| Density | 1–5, default 3 | Initial density 3 |
| Paper types | 1 and 5 | Gap and transparent media in this asset |
| Maximum length field | 100 mm | Verify against this unit; another unit's community capability response reports 200 mm |

The 96-dot head is independently represented in NiimBlue's model table and its recorded D110M capability exchange. Treat the bundled JSON as app defaults, not a live capability query.

## Existing code and local verification

| Project | Local snapshot | Value for Linux work |
| --- | --- | --- |
| [NiimBlueLib](https://github.com/MultiMote/niimbluelib) | `35110a716c960448ee17a9270e4c3a131149866f`, version 0.49.1 | Model lookup, packet parser/encoder, firmware-dependent print tasks, recorded exchanges; MIT license |
| [niimblue-node](https://github.com/MultiMote/niimblue-node) | `e7340dfad69b6aab1c05d2589ca012a7c0ed6313`, version 1.4.1 | Existing CLI and REST service with BLE and serial transports; first candidate to qualify |
| [NiimBridge](https://github.com/KunalBhargava182/OpenNiimbot-NiimBridge) | `ee1de755120f38734680f233a21eb38e1e970bc9` | Kotlin/Android implementation and D110M capture-derived specification; MIT license; useful independent reference |

The old `niimbluelib-headless` repository now redirects to `niimblue-node`.

`npm ci` and `npm run build` succeeded in `research/niimblue-node/`. `node cli.mjs help print` runs and lists `D110M_V4`. The CLI pins **NiimBlueLib 0.47.0-node**, not the separate 0.49.1 checkout. Its installed model table and task selection also contain D110_M and protocol 4 support. Keep these two versions separate when diagnosing behavior.

The separate NiimBlueLib 0.49.1 checkout passed **121 tests, 33 suites, zero failures**, including its recorded D110M firmware 4.23 exchange. That fixture identifies model 2320, protocol 4, a 96-dot head, and 203 dpi. These are offline replay results, not validation of this user's printer or of the CLI's older dependency. Logs are in `artifacts/metadata/niimbluelib-tests.log`, `niimblue-node-build.log`, and `niimblue-cli-help.txt`.

NiimBridge's README claims both transports work, but its `docs/PROTOCOL.md` and `BleTransport.kt` still describe BLE as an unverified fallback. Its strongest documented evidence is Classic SPP traffic from another D110M. Its raw HCI capture is not present in this checkout, so its byte-identical encoder claim is an upstream report, not locally reproduced evidence.

## Protocol findings from community implementations

These details come from the checked-out community implementations and NiimBridge's [protocol specification](https://github.com/KunalBhargava182/OpenNiimbot-NiimBridge/blob/ee1de755120f38734680f233a21eb38e1e970bc9/docs/PROTOCOL.md), not from a recovered implementation inside the current APK.

| Layer | Working specification to validate |
| --- | --- |
| Classic Bluetooth | RFCOMM Serial Port Profile UUID `00001101-0000-1000-8000-00805f9b34fb`; discover the channel rather than assume it |
| BLE candidate | Service `e7810a71-73ae-499d-8c15-faa9aef0c3f2`, characteristic `bef8d6c9-9c21-4c9e-b632-bd58c1009f9f`, notifications and writes without response |
| Frame | `55 55`, command byte, payload-length byte, payload, XOR checksum, `AA AA` |
| Checksum | XOR of command, length, and payload bytes |
| Identity | `0x40 [0x08]`; response `0x48 [0x09,0x10]` identifies model 2320 |
| Raster | 1 bit/pixel, black is 1, MSB first; 96 dots across the head |
| Row encoding | `0x84` blank runs, `0x83` sparse indexed pixels, `0x85` packed bitmap; repeated-row counts and three per-section black-pixel counts |
| V4 job | Label type → density → 9-byte PrintStart → status probe → 13-byte SetPageSize → rows → PageEnd → poll page counter → PrintEnd |

Receivers must buffer fragmented frames and split coalesced frames. Unsolicited line-progress messages must not satisfy an unrelated pending command. Completion must depend on the printed-page counter: NiimBridge reports progress percentages reaching 100 before any page was complete.

NiimBlue's `src/print_tasks/index.ts` selects `D110M_V4` for D110_M **with protocol version 4**, and a B1-style task for the model otherwise. Do not use the older `D110` task just because the product name is similar. If protocol detection is unavailable, keep the result unresolved until a working official-app trace or a controlled test establishes the variant.

The inspected `waitUntilPrintFinishedByStatusPoll` in both library versions has a timeout per request but no overall job deadline. It can poll forever if responses continue without the page counter reaching its target. Add an overall deadline with timer cleanup and controlled cancellation before unattended use. Also serialize status requests so a slow reply cannot accumulate overlapping polls.

## Implementation milestones

1. **Identify this unit.** Record firmware, hardware, model ID, protocol version, printhead width, and media. Start with the built CLI's BLE information query. Release the printer's phone connection for the Linux test. If BLE is unsuitable, qualify Classic SPP through an RFCOMM serial endpoint or a small dedicated transport. The CLI's `serial` option is a serial-port transport, not automatic SPP discovery. Keep Classic and BLE addresses separate. Acceptance: repeatable connect/query/disconnect with logs and no labels consumed.

2. **Qualify one label.** Render a monochrome 30×12 mm printable design at 240×96 pixels; the library's `left` orientation turns it into 240 rows by 96 columns. Use the actual loaded media length if different. Print one asymmetric calibration pattern with edge markers and text, then verify orientation, margin, feed distance, and printed-page confirmation. Start with density 3 and gap media only if that matches the loaded roll. Acceptance: a correctly sized physical label and a second successful job after reconnecting.

3. **Harden a reusable Linux print service.** Reuse the existing encoder and task implementation. Add a validated D110M profile, input bounds, an overall job deadline, cancellation, one job at a time, and actionable media/disconnect errors. Preserve packet logs for diagnostics. Test repeated jobs, two copies, two different labels, lid open, empty roll, disconnect, and cancel. Do not automatically replay a job with uncertain physical completion: that produces duplicate labels. BLE chunking and pacing must follow the actual negotiated transport limits. Acceptance: no indefinite waits, false success, or accidental duplicate retries.

4. **Expose a normal desktop printer.** Add a local IPP Printer Application, with [PAPPL](https://www.msweet.org/pappl/) as the leading framework candidate. It supplies IPP services and raster handling; the NiimBot transport still needs an adapter or bridge to the validated service. Advertise 203 dpi, supported physical label sizes, printable margins, copies, and status. Validate printing through `lp` and an ordinary application. A CUPS backend/filter is an alternative for a specifically targeted legacy installation; [OpenPrinting](https://openprinting.github.io/cups/) supports both Printer Applications and legacy PPD-based drivers.

If the existing Node transport proves awkward on Linux, keep the validated wire protocol and replace that layer using BlueZ D-Bus BLE or RFCOMM. A small Python CLI using a BLE library or a Bluetooth socket is a reasonable fallback. Port the packet state machine and encoder only if reuse proves less maintainable. Neither route calls for a kernel module.

## Commands for the next hardware session

The first two commands only inspect CLI usage and scan nearby BLE advertisements. The information query connects to the chosen device. None of these commands was used to contact the printer during this assessment.

```bash
cd /home/jtd/NiimbotD110M-IPP/research/niimblue-node
node cli.mjs help info
node cli.mjs scan -t ble -n 5000
node cli.mjs info -d -t ble -a 'ACTUAL_BLE_ADDRESS_OR_NAME'
```

If this unit is confirmed as protocol 4, the following is a candidate **physical print** command for a prepared 30×12 mm printable calibration image. `calibration-30x12.png` is a future test asset, not a file created in this assessment. Substitute the actual dimensions and media type as needed. The CLI dimensions describe the image before its `left` rotation.

```bash
node cli.mjs print -d -t ble -a 'ACTUAL_BLE_ADDRESS_OR_NAME' \
  -p D110M_V4 -o left -w 240 -h 96 -q 3 -l 1 -n 1 \
  calibration-30x12.png
```

The BLE dependency uses Noble's native Bluetooth stack; successful compilation and help output do not establish adapter access. Resolve the actual runtime permission or adapter error if one occurs. No system Bluetooth permissions, pairings, services, or CUPS queues were changed here.

If our printer differs from the community implementations, capture one official-app job with Android Bluetooth HCI snoop logging and compare command ordering, payload lengths, geometry, and completion. That is a more direct next diagnostic than unpacking the entire protected application. Android capture availability and the printer's USB data capability are still unverified; the USB-C connector alone is not evidence of a USB print interface.

## Evidence preservation

Recheck `artifacts/metadata/apk-sha256.txt` before further APK work. Upstream checkouts retain their Git commits and lockfiles. The phone app remains installed and unchanged. APKs, native libraries, and decompiler output are local research material excluded by the workspace `.gitignore`; implementation work should reuse the community projects with their notices or independently implement the documented protocol.
