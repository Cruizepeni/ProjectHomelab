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
Linux:   PythoFetchUpdater.AppImage
```

Updater package names remain versioned:

```text
PythoFetchUpdater_<version>_Windows_x86_64.zip
PythoFetchUpdater_<version>_Linux_x86_64.zip
```

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
9. The updater runtime is extracted and verified.
10. PythoFetch launches the updater and exits.
11. PythoFetchUpdater waits for the old PythoFetch process to exit.
12. The current stable runtime is renamed to the temporary backup name.
13. PythoFetchUpdater fetches PythoFetch_Release_Manifest.json directly.
14. The target release ZIP is downloaded and verified.
15. The new stable runtime is extracted and independently verified.
16. The new runtime replaces the stable target.
17. The new runtime is launched with --updated, --updater-pid, and --previous-version.
18. PythoFetchUpdater exits.
19. The new PythoFetch waits for the updater to exit.
20. Post-update compatibility/migration work completes.
21. The temporary old runtime and updater are removed.
22. Normal startup continues.
```

## Temporary Runtime Names

```text
Windows: PythoFetchTemp.exe
Linux:   PythoFetchTemp.AppImage
```

The old runtime is retained until the new runtime has been installed/launched far enough for rollback safety.

## Rollback

If installation fails after the old runtime was moved aside, PythoFetchUpdater attempts to restore and relaunch the previous runtime.

## Build Tools

Updater releases are built using:

```text
Build_PythoFetchUpdater_Windows_x86_64_1.0.0.py
Build_PythoFetchUpdater_Linux_x86_64_1.0.0.py
```

Both use folder-authoritative versioning and the temporary copy/run/remove Build Tool workflow.

See `PythoFetch_Build_Tools.md`.
