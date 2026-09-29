# PythoFetch Build Tools

## Purpose

PythoFetch uses six raw Python Build Tools.

Build Tools remain source scripts and are not compiled into permanent builder executables.

Current Build Tool version:

```text
1.0.0
```

A Build Tool's own version is independent from the feature/component version it builds.

A `Build_*_1.0.0.py` tool can build a later target version until the Build Tool itself actually changes.

No Build Tool automatically bumps its own version, the application version, or a manifest schema.

## Canonical Location

```text
SourceCode/PythoFetch/PythoFetchBuildTools/
```

Current tools:

```text
Build_PythoFetch_Windows_x86_64_1.0.0.py
Build_PythoFetch_Linux_x86_64_1.0.0.py
Build_PythoFetchUpdater_Windows_x86_64_1.0.0.py
Build_PythoFetchUpdater_Linux_x86_64_1.0.0.py
Build_PythoFetchArtDB_1.0.0.py
Build_PythoFetchManifests_1.0.0.py
```

## Application Platform Build Workflow

For an application build, copy the required platform Build Tool into:

```text
SourceCode/PythoFetch/PythoFetch/PythoFetch_<target-version>/
```

Example:

```text
PythoFetch_1.0.0/
├── PythoFetch_1.0.0.py
├── PythoFetchArt_1.0.0.db
└── Build_PythoFetch_Windows_x86_64_1.0.0.py
```

Run the copied Build Tool from that folder.

After the build completes, remove the copied Build Tool.

The canonical copy remains under `PythoFetchBuildTools`.

### Version Authority

The containing version folder is authoritative.

For:

```text
PythoFetch_1.0.7/
```

the target version is:

```text
1.0.7
```

If `PythoFetch_1.0.7.py` still internally declares an older `PYTHOFETCH_VERSION`, the platform Build Tool rewrites that declaration to `1.0.7` before building.

This supports the normal copy-forward source workflow without requiring a manual internal version edit before every build.

### Artwork Database Selection

The application Build Tools require a compatible local:

```text
PythoFetchArt_<version>.db
```

beside the source.

They choose the newest database in the same `X.Y` family as the target application.

Example:

```text
Application target: 1.0.7
Compatible DBs:     1.0.0, 1.0.2, 1.0.5
Selected DB:        1.0.5
```

A database from another compatibility family is not selected.

## Windows Application Build Tool

```text
Build_PythoFetch_Windows_x86_64_1.0.0.py
```

Runs on Windows.

Pinned application-build dependency:

```text
PyInstaller 6.22.3
```

Application icon source:

```text
Resources/Icons/Features/PythoFetch/Icon_PythoFetch.ico
```

The tool can use a valid local icon when present and otherwise uses the configured ProjectHomelab icon source.

It performs source/build checks and produces:

```text
PythoFetch_<version>_Windows_x86_64.zip
└── PythoFetch.exe
```

The runtime filename inside the release remains stable.

## Linux Application Build Tool

```text
Build_PythoFetch_Linux_x86_64_1.0.0.py
```

Runs on Linux.

Pinned build dependencies include:

```text
PyInstaller 6.22.3
Pillow 11.3.0
appimagetool 1.9.1
```

The Type 2 AppImage runtime is pinned by build identifier, SHA-256, and byte size.

Application icon source:

```text
Resources/Icons/Features/PythoFetch/Icon_PythoFetch.png
```

The Build Tool:

```text
1. validates the target folder/source/database
2. normalizes the source version if needed
3. prepares pinned build dependencies
4. builds the PyInstaller payload
5. builds the AppDir
6. creates the Type 2 AppImage
7. verifies the embedded runtime
8. tests the AppImage
9. creates the versioned release ZIP
```

Output:

```text
PythoFetch_<version>_Linux_x86_64.zip
└── PythoFetch.AppImage
```

PythoFetch itself remains an AppImage on Linux.

## Updater Platform Build Workflow

Updater Build Tools use the same copy/run/remove rule.

Copy the required updater Build Tool into:

```text
SourceCode/PythoFetch/PythoFetchUpdater/
PythoFetchUpdater_<target-version>/
```

The containing updater folder is authoritative for the updater target version.

If the source still declares an older `PYTHOFETCH_UPDATER_VERSION`, the Build Tool normalizes it before building.

Remove the copied Build Tool after the build.

## Windows Updater Build Tool

```text
Build_PythoFetchUpdater_Windows_x86_64_1.0.0.py
```

Runs on Windows.

Pinned dependency:

```text
PyInstaller 6.22.3
```

Shared updater icon:

```text
Resources/Icons/Shared/Updater/Icon_Updater.ico
```

Output:

```text
PythoFetchUpdater_<version>_Windows_x86_64.zip
└── PythoFetchUpdater.exe
```

## Linux Updater Build Tool

```text
Build_PythoFetchUpdater_Linux_x86_64_1.0.0.py
```

Runs on Linux.

Pinned dependency:

```text
PyInstaller 6.22.3
```

The Linux updater is intentionally built as a plain one-file PyInstaller ELF executable rather than an AppImage.

The Build Tool:

```text
1. validates the updater target folder and source
2. normalizes the source updater version if needed
3. prepares the pinned PyInstaller build environment
4. tests the updater source --version command
5. builds a one-file executable named PythoFetchUpdater
6. verifies executable permissions and the ELF magic header
7. tests the compiled PythoFetchUpdater --version command
8. creates the versioned updater ZIP
9. verifies the ZIP contains exactly one PythoFetchUpdater payload
10. reports ZIP and executable SHA-256 hashes and byte sizes
```

The Linux updater build does not use:

```text
Pillow
appimagetool
an AppDir
an AppImage runtime
FUSE packaging
```

Output:

```text
PythoFetchUpdater_<version>_Linux_x86_64.zip
└── PythoFetchUpdater
```

Keeping the transient updater as a plain executable avoids introducing a second AppImage/FUSE lifecycle while it replaces `PythoFetch.AppImage`.

## Art Database Build Tool

```text
Build_PythoFetchArtDB_1.0.0.py
```

This tool is not copied into another folder.

Run it directly from:

```text
SourceCode/PythoFetch/PythoFetchBuildTools/
```

It validates/merges:

```text
PythoFetchArtAssets/ArtAssetsNeofetch
PythoFetchArtAssets/ArtAssetsPythoFetch
```

and creates a versioned SQLite database under:

```text
PythoFetchArtAssets/ArtAssetsDB/
```

It also manages:

```text
PythoFetchArtDB_Manifest.json
```

Current fixed schema values inside the tool are:

```text
Database schema: 1
Manifest schema: 1
```

The Build Tool does not automatically bump either.

See `PythoFetch_Art_Manager.md`.

## Manifest Build Tool

```text
Build_PythoFetchManifests_1.0.0.py
```

This Build Tool is copied temporarily into one of exactly three PythoFetch roots:

```text
SourceCode/PythoFetch
Releases/PythoFetch
Resources/FirstParty/PythoFetch
```

Run it there, then remove the copied tool.

The tool normally auto-detects its environment from the files/folders around it.

If auto-detection cannot determine exactly one environment it asks:

```text
Auto Detect Failed.
Is this for SourceCode, Releases or Resources?
>
```

Accepted aliases include:

```text
source
sourcecode
release
releases
resource
resources
```

The tool rebuilds manifests from the actual contents present rather than relying on an old manifest as the source of truth.

The current generated manifest schema is:

```text
1
```

It does not bump schema values.

### SourceCode Mode

Generates/rebuilds:

```text
PythoFetch_Source_Manifest.json
PythoFetch/PythoFetch_Manifest.json
PythoFetchUpdater/PythoFetchUpdater_Manifest.json
PythoFetchArtAssets/PythoFetchArtAssets_Manifest.json
PythoFetchArtAssets/ArtAssetsDB/PythoFetchArtDB_Manifest.json
PythoFetchBuildTools/PythoFetchBuildTools_Manifest.json
```

### Releases Mode

Generates/rebuilds:

```text
PythoFetch_Release_Manifest.json
```

It reads actual versioned release ZIPs and records package/runtime verification data.

### Resources Mode

Generates/rebuilds:

```text
PythoFetch_Resources_Manifest.json
PythoFetchUpdater/PythoFetchUpdater_Release_Manifest.json
Resources/FirstParty/FirstParty_Resources_Manifest.json
Resources/Resources_Manifest.json
```

The last two are generic navigation routers and deliberately contain only navigation information.

## Build Order for a PythoFetch Application Release

For an application source change:

```text
1. Update PythoFetch_<version>.py.
2. Ensure a compatible PythoFetchArt_<version>.db is beside it.
3. Copy the Windows or Linux application Build Tool into the version folder.
4. Run the Build Tool.
5. Remove the copied Build Tool.
6. Move/publish the resulting release ZIP under Releases/PythoFetch.
7. Run the Manifest Build Tool in Releases/PythoFetch.
8. Remove the copied Manifest Build Tool.
9. Run the Manifest Build Tool in SourceCode/PythoFetch after source changes.
10. Remove the copied Manifest Build Tool.
```

If updater packages or resource structure have not changed, the updater does not need to be rebuilt just because the PythoFetch application source changed.

If the Linux updater itself changes, rebuild `PythoFetchUpdater_<version>_Linux_x86_64.zip` and rerun the Manifest Build Tool in `Resources/FirstParty/PythoFetch` so the updater package/executable verification data is regenerated.

## Current 1.0.0 Resource-Entry Correction

The current PythoFetch 1.0.0 source must directly use:

```text
Resources/FirstParty/PythoFetch/PythoFetch_Resources_Manifest.json
```

for updater-resource discovery.

Application builds compiled from a source that instead begins at:

```text
Resources/Resources_Manifest.json
```

must be rebuilt from the corrected PythoFetch 1.0.0 source if they are expected to work with the current navigation-only generic routers.

This correction does not require a Build Tool version change.

It also does not require rebuilding PythoFetchUpdater because the updater has its own direct PythoFetch release-manifest entry point.
