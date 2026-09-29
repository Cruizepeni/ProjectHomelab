# PythoFetch

## Purpose

PythoFetch is ProjectHomelab's Python-native static system-information fetch application.

It collects a snapshot of the current machine, resolves matching operating-system artwork, and presents the result through:

- the ProjectHomelab terminal UI
- NeoFetch-style classic output
- headless JSON or text output

PythoFetch is a snapshot tool rather than a live hardware monitor.

## Current Version

```text
PythoFetch 1.0.0
```

The current artwork database schema is:

```text
1
```

The current manifest schema is:

```text
1
```

Neither application versions nor schema values are automatically bumped.

## Canonical Manifest Entry Points

PythoFetch has three top-level feature manifests, one for each repository environment.

```text
Release:
Releases/PythoFetch/PythoFetch_Release_Manifest.json

Resources:
Resources/FirstParty/PythoFetch/PythoFetch_Resources_Manifest.json

SourceCode:
SourceCode/PythoFetch/PythoFetch_Source_Manifest.json
```

These are independent entry points. PythoFetch does not begin at a generic ProjectHomelab root manifest and crawl toward itself.

### Release Entry Point

The packaged application checks:

```text
Releases/PythoFetch/PythoFetch_Release_Manifest.json
```

directly when checking for a newer PythoFetch release.

### Resource Entry Point

When PythoFetch needs a first-party runtime resource such as PythoFetchUpdater, it starts directly at:

```text
Resources/FirstParty/PythoFetch/PythoFetch_Resources_Manifest.json
```

It does not use:

```text
Resources/Resources_Manifest.json
Resources/FirstParty/FirstParty_Resources_Manifest.json
```

Those generic manifests are repository-navigation aids for callers that do not already know where a feature lives.

### SourceCode Entry Point

The canonical SourceCode entry point is:

```text
SourceCode/PythoFetch/PythoFetch_Source_Manifest.json
```

This is primarily development and repository-navigation metadata.

The running Python source does not need to traverse this manifest to recover an artwork database. Because it already knows exactly which component it needs, missing-DB recovery directly uses:

```text
SourceCode/PythoFetch/PythoFetchArtAssets/ArtAssetsDB/
PythoFetchArtDB_Manifest.json
```

## Supported Host Operating Systems

PythoFetch 1.0.0 has native collectors for:

```text
Windows
Linux
macOS
```

Python host dispatch is:

```text
Windows -> Windows collector
Linux   -> Linux collector
Darwin  -> macOS collector
```

Artwork support and host collector support are separate concepts.

## Runtime Modes

### ProjectHomelab TUI

No arguments:

```text
PythoFetch
```

The TUI renders once and waits for input.

Normal controls:

```text
Enter  Exit
U      Open update confirmation when an update is available
Esc    Cancel from update confirmation
```

### Classic

```text
PythoFetch --classic
```

Prints a NeoFetch-style one-shot view and exits.

### Headless

```text
PythoFetch --headless
```

Headless defaults to all information in JSON.

Selectors:

```text
--info
--art
--all
```

Formats:

```text
--format json
--format text
```

Examples:

```text
PythoFetch --headless --info --format json
PythoFetch --headless --art --format json
PythoFetch --headless --all --format json
PythoFetch --headless --all --format text
```

### Other Commands

```text
PythoFetch --version
PythoFetch --help
PythoFetch --update
```

Internal post-update arguments:

```text
--updated
--updater-pid
--previous-version
```

## Artwork Database Resolution

PythoFetch looks for local files matching:

```text
PythoFetchArt_<version>.db
```

and validates candidates before use.

When running as Python source:

```text
1. Search runtime/source directories for local PythoFetchArt_<version>.db files.
2. Sort candidate versions newest-first.
3. Validate candidate SQLite databases.
4. Use the newest valid local database.
5. If no valid local database exists, fetch PythoFetchArtDB_Manifest.json directly.
6. Ignore manifest database versions whose schema_version does not match ART_DATABASE_SCHEMA_VERSION.
7. Choose the newest compatible database version.
8. Download the database using its download_url.
9. Verify size_bytes and sha256.
10. Validate the downloaded SQLite database and expected version.
11. Store/use the recovered database.
```

The Python-source recovery path deliberately bypasses `PythoFetch_Source_Manifest.json`.

When frozen/packaged, a missing or invalid bundled database is treated as a broken installation and PythoFetch asks for reinstallation rather than downloading a loose replacement database.

## Release Packaging

Release ZIP names remain versioned:

```text
PythoFetch_<version>_Windows_x86_64.zip
PythoFetch_<version>_Linux_x86_64.zip
```

Installed/runtime filenames remain stable:

```text
Windows: PythoFetch.exe
Linux:   PythoFetch.AppImage
```

The stable runtime name does not encode the application version.

## Update Discovery

The release check begins directly at:

```text
Releases/PythoFetch/PythoFetch_Release_Manifest.json
```

If a newer compatible release exists, PythoFetch can offer an update.

When the user confirms, updater discovery begins directly at:

```text
Resources/FirstParty/PythoFetch/PythoFetch_Resources_Manifest.json
```

The resource manifest points to:

```text
PythoFetchUpdater_Release_Manifest.json
```

That manifest is verified using the hash/size recorded in `PythoFetch_Resources_Manifest.json`.

The updater release manifest then provides the package and executable verification data for the selected compatible updater.

Current updater runtime names are:

```text
Windows: PythoFetchUpdater.exe
Linux:   PythoFetchUpdater
```

The Linux updater is a plain PyInstaller-built ELF executable rather than an AppImage. The application itself remains `PythoFetch.AppImage`.

### Linux Updater Launch Behavior

Linux PythoFetch supports two update handoff cases.

When PythoFetch is already running from a persistent user terminal, the updater can continue from that terminal.

When the AppImage opened PythoFetch through its own temporary terminal, PythoFetch starts PythoFetchUpdater in a separate terminal before exiting. This keeps the updater's terminal alive after the original PythoFetch terminal closes.

The updater downloads, extracts, and verifies the new AppImage into a staging path before the installed AppImage is renamed. After the old PythoFetch payload exits, the updater moves the existing AppImage to `PythoFetchTemp.AppImage`, installs the verified staged AppImage at the stable `PythoFetch.AppImage` path, and launches it with the internal post-update arguments.

See `PythoFetch_Updater.md` for the full lifecycle.

## Generic ProjectHomelab Routers

These generic routers are intentionally not PythoFetch runtime dependencies:

```text
Resources/Resources_Manifest.json
Resources/FirstParty/FirstParty_Resources_Manifest.json
```

Their job is discovery.

For example, an AI or developer beginning at the Resources root can navigate:

```text
Resources_Manifest.json
        ->
FirstParty_Resources_Manifest.json
        ->
PythoFetch_Resources_Manifest.json
```

Generic router references contain only navigation data:

```text
file
path
download_url
```

They intentionally do not contain payload verification fields such as:

```text
sha256
size_bytes
```

Once the feature-specific manifest is reached, normal manifest verification data is used where applicable.

## Source Tree

```text
SourceCode/PythoFetch/
├── PythoFetch_Source_Manifest.json
├── PythoFetch/
│   ├── PythoFetch_Manifest.json
│   └── PythoFetch_<version>/
│       ├── PythoFetch_<version>.py
│       └── PythoFetchArt_<compatible-version>.db
├── PythoFetchUpdater/
│   ├── PythoFetchUpdater_Manifest.json
│   └── PythoFetchUpdater_<version>/
│       └── PythoFetchUpdater_<version>.py
├── PythoFetchArtAssets/
│   ├── PythoFetchArtAssets_Manifest.json
│   ├── ArtAssetsDB/
│   │   ├── PythoFetchArtDB_Manifest.json
│   │   └── PythoFetchArt_<version>.db
│   ├── ArtAssetsNeofetch/
│   └── ArtAssetsPythoFetch/
└── PythoFetchBuildTools/
    ├── PythoFetchBuildTools_Manifest.json
    ├── Build_PythoFetch_Windows_x86_64_1.0.0.py
    ├── Build_PythoFetch_Linux_x86_64_1.0.0.py
    ├── Build_PythoFetchUpdater_Windows_x86_64_1.0.0.py
    ├── Build_PythoFetchUpdater_Linux_x86_64_1.0.0.py
    ├── Build_PythoFetchArtDB_1.0.0.py
    └── Build_PythoFetchManifests_1.0.0.py
```

## Resources Tree

```text
Resources/
├── Resources_Manifest.json
└── FirstParty/
    ├── FirstParty_Resources_Manifest.json
    └── PythoFetch/
        ├── PythoFetch_Resources_Manifest.json
        └── PythoFetchUpdater/
            ├── PythoFetchUpdater_Release_Manifest.json
            ├── PythoFetchUpdater_<version>_Windows_x86_64.zip
            └── PythoFetchUpdater_<version>_Linux_x86_64.zip
```

The Linux updater ZIP contains the plain executable:

```text
PythoFetchUpdater_<version>_Linux_x86_64.zip
└── PythoFetchUpdater
```

## Release Tree

```text
Releases/PythoFetch/
├── PythoFetch_Release_Manifest.json
├── PythoFetch_<version>_Windows_x86_64.zip
└── PythoFetch_<version>_Linux_x86_64.zip
```

## Build System

PythoFetch uses six Build Tools.

The four platform build tools are copied temporarily into the matching version folder, run there, then removed.

The manifest Build Tool is copied temporarily into the SourceCode, Releases, or Resources PythoFetch root, run there, then removed.

The Art DB Build Tool is the exception: it runs directly from `PythoFetchBuildTools`.

See `PythoFetch_Build_Tools.md`.

## NeoFetch Lineage

PythoFetch is a separate Python implementation inspired by NeoFetch.

NeoFetch-derived artwork remains attributed to NeoFetch and its license material is retained in the artwork source tree.
