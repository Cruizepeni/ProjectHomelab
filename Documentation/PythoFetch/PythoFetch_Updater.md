# PythoFetchUpdater

## Purpose

PythoFetchUpdater is the external replacement helper used by packaged PythoFetch releases.

Current updater version:

```text
1.0.0
```

Its version is independent from the PythoFetch application patch version.

## Direct Manifest Entry Point

PythoFetchUpdater directly uses:

```text
Releases/PythoFetch/PythoFetch_Release_Manifest.json
```

It does not use ProjectHomelab's generic resource routers.

## Compatibility

PythoFetch selects an updater by `X.Y` compatibility family.

Example:

```text
PythoFetch 1.0.7
PythoFetchUpdater 1.0.3
Compatibility family 1.0
```

The updater release manifest explicitly records `compatibility_family`.

## Stable Updater Runtime Names

```text
Windows: PythoFetchUpdater.exe
Linux:   PythoFetchUpdater
```

The Linux updater is a standalone PyInstaller-built ELF executable with separate builds for x86_64 and arm64.

It is deliberately not packaged as an AppImage. PythoFetch itself remains an AppImage on Linux, while the transient updater runs as a plain executable so the replacement path does not create a second AppImage/FUSE lifecycle.

Updater package names remain versioned:

```text
PythoFetchUpdater_<version>_Windows_x86_64.zip
PythoFetchUpdater_<version>_Linux_x86_64.zip
PythoFetchUpdater_<version>_Linux_arm64.zip
```

## Linux Updater Handoff

When Linux PythoFetch is started from an existing terminal, the updater continues from that terminal.

When PythoFetch was started through its AppImage auto-terminal path, PythoFetch opens a separate terminal for PythoFetchUpdater before the original PythoFetch terminal closes.

This prevents the updater from inheriting terminal file descriptors that disappear when the original temporary terminal exits.

The updater receives the installed AppImage path through PythoFetch's resolved runtime target and performs the replacement outside the AppImage payload.

## Application Update Lifecycle

```text
1. PythoFetch checks PythoFetch_Release_Manifest.json directly.
2. A newer application release is found.
3. The user confirms the update.
4. PythoFetch fetches PythoFetch_Resources_Manifest.json directly.
5. PythoFetch resolves PythoFetchUpdater_Release_Manifest.json.
6. The updater manifest reference is verified.
7. PythoFetch selects the newest updater compatible with its X.Y family.
8. The updater ZIP is downloaded and verified.
9. The updater runtime is extracted and independently verified.
10. PythoFetch launches the updater and exits.
11. On Linux, an auto-terminal PythoFetch launch hands the updater to a separate terminal; an existing user terminal can be reused.
12. PythoFetchUpdater fetches PythoFetch_Release_Manifest.json directly.
13. The target release ZIP is downloaded and verified.
14. The new stable runtime is extracted to a staging path and independently verified before the installed runtime is touched.
15. PythoFetchUpdater waits for the old PythoFetch payload process to exit.
16. The current stable runtime is renamed to the temporary backup name.
17. The verified staged runtime replaces the stable target.
18. Linux executable permissions are restored on the new AppImage.
19. The new runtime is launched with --updated, --updater-pid, and --previous-version.
20. PythoFetchUpdater exits.
21. The new PythoFetch waits for the updater to exit.
22. Post-update compatibility/migration work completes.
23. The temporary old runtime and updater are removed.
24. Normal startup continues.
```

The target release is therefore downloaded, extracted, and verified before the installed runtime is moved aside.

## Temporary Runtime Names

```text
Windows: PythoFetchTemp.exe
Linux:   PythoFetchTemp.AppImage
```

The old runtime is retained until the new runtime has been installed/launched far enough for rollback safety.

## Rollback

If installation fails after the old runtime was moved aside, PythoFetchUpdater attempts to restore and relaunch the previous runtime.

Failures that occur while downloading, extracting, or verifying the new release happen before the installed runtime is renamed.

## Build Tools

Updater releases are built using:

```text
Build_PythoFetchUpdater_Windows_x86_64_1.0.0.py
Build_PythoFetchUpdater_Linux_x86_64_1.0.0.py
Build_PythoFetchUpdater_Linux_arm64_1.0.0.py
```

All three use folder-authoritative versioning and the temporary copy/run/remove Build Tool workflow.

The Windows updater is packaged as `PythoFetchUpdater.exe`.

Both Linux updater variants are packaged as the plain executable `PythoFetchUpdater` inside architecture-specific ZIPs. Runtime platform detection supports Linux x86_64/AMD64 and Linux arm64/aarch64.

See `PythoFetch_Build_Tools.md`.
