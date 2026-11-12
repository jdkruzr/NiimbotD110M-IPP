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
page events). Nine local regression tests pass. The C build passes
`-Wall -Wextra`. A separate fake service uses NIIMBOT_FAKE=1 and
NIIMBOT_PORT=8632; never enable fake mode on the live service.

Development limitations still requiring work: live error/status mapping,
physical cancellation/link-loss qualification, crash/restart acceptance,
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
