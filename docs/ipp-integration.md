# Local IPP integration (development)

The local PAPPL application builds with `make -C ipp`. Dependencies are
`libpappl-dev`, `libcups2-dev`, Node 22+, Python 3, and the pinned patched
NiimBlue checkout described in qualification-status.md.

`./scripts/niimbot-setup` installs/enables the systemd user unit and creates
`Niimbot_D110M` without changing the default printer. It reads
`~/.config/niimbot/config.json` with `address` and `channel`. Pair using
BlueZ first; disconnect the phone app before printing.

```
lp -d Niimbot_D110M -o PageSize=12x40mm.Borderless label.pdf
journalctl --user -u niimbot-ipp
systemctl --user restart niimbot-ipp
```

The service binds only 127.0.0.1:8631. Stock is fixed to 12x40 mm gaps,
203 dpi, density 3. PAPPL image conversion and the CUPS raster pipeline
expand copies; the worker sends each received page exactly once.
95x319 rasters arising from PAPPL's physical-unit rounding are padded
with white to 96x320, not rescaled. Each complete job is buffered before
Bluetooth transmission and limited to 100 physical pages.

Worker v1 uses a JSON manifest with `version:1` and an ordered `pages`
array of files, each 30720 grayscale bytes (96x320, white=255). JSON-line
events report connected, transmitting, progress, completed, or error.
The supervisor requires a completed event with the expected page count
and successful exit. Journals under `~/.local/state/niimbot` record uncertain
execution before transmission. They are diagnostic records, never replay queues.
The systemd unit kills the whole process group on shutdown.

## Packaging

`packaging/build-deb.sh` builds an Ubuntu amd64 development .deb under
`artifacts/packages/`. It bundles the current built Node dependency tree;
it is not yet a clean-room/reproducible release build. It does not install
or enable a printer automatically. After installing, run
`/usr/lib/niimbot/scripts/niimbot-setup` as the desktop user, with the config
file already present. The package has not yet been installation-tested.

## Validation and remaining work

A physical CUPS PNG job completed and the user confirmed orientation,
text, borders and feed. Fake-worker tests exercised direct IPP two-copy
images and a two-page PDF with two collated copies via CUPS (four physical
page events). The initial nine local regression tests passed; see the safety additions below. The C build passes
`-Wall -Wextra`. A separate fake service uses NIIMBOT_FAKE=1 and
NIIMBOT_PORT=8632; never enable fake mode on the live service.

Development limitations still requiring work: live error/status mapping,
additional hardware failure qualification,
IPP progress counters (PAPPL counts raster processing before physical
completion), release packaging and notices audit, application-dialog test,
and a label-specific self-test callback. Do not regard this as a fully
qualified unattended print service yet.

## Remove

Cancel pending jobs first, then:

```
lpadmin -x Niimbot_D110M
systemctl --user disable --now niimbot-ipp
rm ~/.config/systemd/user/niimbot-ipp.service
systemctl --user daemon-reload
```

Configuration and journals remain for diagnosis; the original CLI remains
available in the workspace.

The physical offline test returned Host is down and reached IPP aborted/CUPS terminal state without replay. It exposed a repeated end-job cleanup crash, now fixed and retested; the service remained active afterward. No pending live jobs remained.

## Job safety hardening

The supervisor now uses atomic, fsynced journals and a user-wide execution lock.
Only an explicit completion event with the exact page count plus successful
worker exit is success. Missing events, malformed output, timeouts, cancellation,
and link loss fail closed. An interrupted job with possible output creates a
recovery hold; reconnecting Bluetooth does not release it. Reusing the same job
directory cannot replay an attempt.

Linux parent-death guards kill the bridge and Node worker if their parent is
killed. The C callback also arms a parent-death signal for the supervisor, handles
waitpid errors explicitly, uses a monotonic deadline, and will not transmit a
job PAPPL has already marked aborted. The systemd unit still kills its entire
control group during shutdown. Node's absolute path is captured by setup so
NVM-based installations also work outside the interactive shell.

An unclean service exit leaves a durable `service-active` marker in its spool.
The next startup creates `recovery-required` and refuses new jobs. This also
covers a crash after physical completion but before CUPS receives the result.
The gate is intentionally conservative: it is not an exactly-once protocol with
the printer. A graceful idle restart does not create a hold.

After inspecting the printer and any labels, list uncertain attempts:

```
python3 ipp/supervise.py recover
python3 ipp/supervise.py recover --acknowledge niimbot-job-EXACT_NAME.json
```

Acknowledgement records the inspection decision; it neither reprints the job nor
claims how many labels emerged. For an unclean-service hold, first cancel old
CUPS jobs, stop the service, inspect/acknowledge uncertain attempts, then clear
the hold and start it again:

```
cancel -a Niimbot_D110M
systemctl --user stop niimbot-ipp
# Inspect the printer; use the recover commands above for listed attempts.
rm -f ~/.local/state/niimbot/spool/recovery-required
systemctl --user start niimbot-ipp
```

Use the configured XDG state/spool location if it differs from the default.
Resubmit only the labels you actually want. Do not delete journals to bypass a
hold. Successful historical jobs are retained for diagnosis, not replay.

Tests: `python3 -m unittest discover -s tests -p 'test_*.py' -v` runs ten tests
covering supervision, deadlines, missing completion, link loss, locking,
explicit recovery, SIGTERM, SIGKILL and full IPP cancellation/restart. These use
isolated fake printers, temporary state, and loopback ports; they never connect
to Bluetooth or modify the installed CUPS queue. The existing nine Node tests
also pass. Test scenarios and shortened deadlines only apply in explicit fake
mode.

Physical CUPS cancellation was tested during a two-label job. CUPS reached
canceled, the worker stopped, the uncertainty hold engaged, and the user
confirmed no label emerged and the printer was idle. That inspected test
attempt was explicitly acknowledged. This establishes the observed test outcome,
not a guarantee that cancelling can stop labels already buffered by the printer.

A second two-label job was interrupted with `bluetoothctl disconnect` during
transmission. The worker reported the lost connection, IPP reached aborted,
and no automatic retry occurred. The user reported no label output. A subsequent
information-only RFCOMM reconnect succeeded while the uncertainty hold remained
in place. The inspected test job was then acknowledged; the live queue has no
pending jobs. Physical link loss is therefore tested, while partial-output and
late-cancel behavior remain conservatively classified as uncertain.

Safety test evidence is saved locally in `artifacts/metadata/safety-*.log`.
The development package is now `0.1.0~dev2`; installation/upgrade qualification
and the broader status/reporting work remain separate tasks.
