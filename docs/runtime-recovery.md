# Niimbot runtime payload recovery

Rooted, read-only access to the running NIIMBOT 6.7.0 process recovered six application DEX files totaling **61,312,404 bytes and 45,216 class definitions** on 2026-11-12. Every recovered file retains a valid original SHA-1 signature field and Adler-32 checksum. No header repairs were necessary. A separate 284-byte, one-class generated DEX was also found.

The installed application, process memory, and application data were not modified. No process was stopped or restarted, no debugger was attached, and no Frida server or helper binary was installed on the phone. Frida 17.26.2 and its matching ARM64 server were prepared locally but not used. The user enabled Shell root access through KernelSU; `su -c id` then returned UID 0 in the `ksu` SELinux domain.

## Recovery method

The main app was already running as PID 28871. Its similarly named child, PID 28895, had only two threads; extraction targeted the main process. Root could read `/proc/28871/maps` and `/proc/28871/mem` without attaching through ptrace.

The first scan of unnamed readable mappings found only the tiny generated DEX. Extending the scan to Scudo allocator mappings found all six application DEX files within the single mapping `7a07d80000-7a0b7ff000`. Their standard `dex\n037\0` headers were intact. Scanning for damaged headers was enabled on the second pass, but was not needed for these files.

`scripts/dump_runtime_dex.py` uses rooted ADB and Toybox `dd` to read candidate regions, checks DEX header and table bounds, and saves only plausible DEX files. It does not persist complete heap snapshots. The second scan inspected 406,306,816 bytes with no read errors; it deliberately excludes most runtime heaps and unrelated file mappings, so it is not a claim to have enumerated every possible dynamically loaded DEX. This was a live read, not an atomic process snapshot; matching file checksums substantiate the consistency of the recovered files.

| Application DEX address | Bytes | Class definitions | SHA-256 prefix |
| --- | --- | --- | --- |
| `7a07d82000` | 11,364,488 | 7,916 | `917f840bdac9` |
| `7a08859000` | 13,234,564 | 9,358 | `7b1591bbbbbd` |
| `7a094f9000` | 12,764,672 | 10,630 | `7fa528ad58ff` |
| `7a0a126000` | 13,241,796 | 9,018 | `fdfc23608b53` |
| `7a0adc7000` | 10,342,696 | 7,943 | `fb2aabe423bc` |
| `7a0b7a5000` | 364,188 | 351 | `b45ed381af82` |

Full hashes, memory addresses, class counts, and checksum results are in `artifacts/runtime/dex-pass2/manifest.json`. Addresses and PIDs are specific to this process lifetime.

## Decompiler results

JADX 1.5.6 processed the six application DEX files and produced 24,178 Java source files in `decompiled/runtime-jadx/sources/`. Source-file counts differ from DEX class-definition counts because nested classes and other generated structures may be combined. JADX exited 3 with 207 errors; recovered source is useful but individual difficult methods still need CFR or instruction-level verification.

dex2jar 2.4 converted the SDK-bearing DEX, `7a094f9000-7fa528ad58ff.dex`, into `decompiled/runtime-sdk.jar`. CFR 0.152 recovered selected packet, Bluetooth, factory, and D110 task classes under `decompiled/runtime-cfr/`. Several older D110 methods still have control-flow reconstruction warnings. Neither successful checksum verification nor readable source establishes that every protected/native method is recovered as Java.

## Printer code now available

Paths below are relative to `decompiled/runtime-jadx/sources/com/gengcon/www/jcprintersdk/` unless otherwise indicated.

| Entry point | Confirmed observation |
| --- | --- |
| `data/NiimbotSppPacket.java`, `toBytes()` | Frames begin `55 55`, include command, length, and payload, XOR those bytes for the checksum, and end `AA AA`; corroborated in CFR |
| `factory/connecttype/BluetoothDeviceAttributes.java`, `createSocket()` | Uses `createInsecureRfcommSocketToServiceRecord()` and standard SPP UUID `00001101-0000-1000-8000-00805F9B34FB`; corroborated in CFR |
| `printer/BitmapUtil.java`, `generatePrintData()` | Chooses blank-line encoding when there are no black pixels, coordinate encoding below six pixels, and bitmap encoding otherwise |
| `factory/printerfactory/D110Factory.java` | Contains older D110 task dispatch keyed by the SDK's internal protocol selector; do not equate that selector with the community wire-version number |
| `data/DataSend.java` | Contains print-start variants, including a nine-byte payload in `printStartInstructionSendV5()` |
| `printer/printtask/ProtocolV3PrinterTask.java` through `ProtocolV6PrinterTask.java` | Multiple print-task generations are available for tracing |
| `controller/AutoPrinter.java`, `factory/printerfactory/CommonFactory.java` | Additional factory/task selection paths; the older D110 factory alone is insufficient to establish D110M behavior |
| `com/niimbot/niimbot_print_sdk/PrintSDKManager.java` under the source root | Flutter bridge imports and calls the Java printer SDK |

Naming is a trap here: the community's `D110M_V4` uses a nine-byte PrintStart, while the official SDK method named `printStartInstructionSendV4()` builds seven bytes and its `V5()` builds nine. Compare packet bytes and call paths rather than assuming similarly named versions are equivalent. The D110M's complete model/firmware dispatch and current live protocol remain to be verified.

These findings directly corroborate several community protocol details. They do not demonstrate that this user's printer has received a successful Linux print job. Native `.so` implementations and Flutter's `libapp.so` also remain outside this DEX recovery.

## Reproduction

Confirm the current main-process PID and root identity before extracting again. Use a new output directory; the script refuses to reuse one. Example for the observed process lifetime:

```bash
adb -s ZP22237HZZ shell su -c id
adb -s ZP22237HZZ shell ps -A -o PID,NAME
python3 scripts/dump_runtime_dex.py \
  --serial ZP22237HZZ --pid 28871 \
  --include-allocators --recover-headers \
  --output artifacts/runtime/dex-new-snapshot
```

The scanner verifies the process command line before reading memory. A future version with erased headers, compact DEX, DEX 041 containers, method-level restoration, or native virtualization may require a different method. The successful result here came from intact DEX 037 buffers already present in the app's allocator memory.
