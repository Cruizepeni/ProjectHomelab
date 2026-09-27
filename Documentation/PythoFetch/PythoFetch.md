# PythoFetch

## Purpose

PythoFetch is a cross-platform static system-information fetcher for ProjectHomelab.

It collects a snapshot of the current machine, resolves matching operating-system artwork, and presents the result through one of three interfaces:

- ProjectHomelab terminal UI
- NeoFetch-style classic output
- headless JSON or plain-text output

PythoFetch is intentionally a snapshot tool rather than a live hardware monitor. It reports the machine state at the time it is run and then exits, except for the interactive terminal UI waiting for the user to close it.

## NeoFetch Lineage

PythoFetch was created as a Python-native successor inspired by NeoFetch.

The name reflects that relationship:

- `Pytho` refers to the Python implementation.
- `Fetch` retains the familiar system-fetch concept and acknowledges NeoFetch as the original inspiration.

PythoFetch does not run the original NeoFetch Bash application as its system-information backend. System collection, rendering, database handling, headless output, and updating are implemented in Python.

NeoFetch remains important to PythoFetch in two ways:

1. Its visual layout inspired PythoFetch's classic renderer.
2. Its operating-system ASCII artwork is used as the initial artwork catalogue.

The NeoFetch artwork is extracted from the upstream `get_distro_ascii` catalogue and converted into PythoFetch's editable art-source and SQLite database format.

The original NeoFetch project is available at:

```text
https://github.com/dylanaraps/neofetch
```

NeoFetch is distributed under the MIT License. The ProjectHomelab NeoFetch-derived artwork source retains the relevant license material.

## Current Version

```text
PythoFetch 1.0.0
```

## Supported Host Operating Systems

PythoFetch 1.0.0 has native system collectors for:

- Windows
- Linux
- macOS

The runtime collector currently dispatches by the host value returned by Python's `platform.system()`:

```text
Windows -> Windows collector
Linux   -> Linux collector
Darwin  -> macOS collector
```

A genuinely new host operating system requires a new collector in PythoFetch. Adding artwork alone does not add system-information support for a new host OS.

## What PythoFetch Collects

The exact fields available vary by operating system and by what the host exposes.

The normalized snapshot can include:

- provider
- username
- hostname
- operating system
- host / machine model
- kernel
- build
- uptime
- package count where available
- shell
- display resolution
- desktop environment
- window manager
- window-manager theme
- desktop theme
- icon theme
- terminal
- terminal font
- CPU
- physical core count
- logical core count
- CPU maximum frequency
- GPU information
- memory usage
- primary disk information
- architecture

Linux snapshots can also include:

- distribution ID
- distribution-family information

PythoFetch deliberately tolerates unavailable fields. Missing values are omitted from the user-facing presentation instead of causing the entire fetch to fail.

## Runtime Flow

A normal PythoFetch run follows this general sequence:

```text
Start PythoFetch
        |
        v
Parse command-line mode
        |
        v
Detect host operating system
        |
        v
Collect normalized system snapshot
        |
        v
Locate and validate art database
        |
        v
Resolve artwork from aliases / fallbacks
        |
        v
Render TUI, classic output, or headless payload
```

## Artwork Resolution

Artwork is stored in a versioned SQLite database named:

```text
PythoFetchArt_<version>.db
```

PythoFetch validates an art database before using it.

Validation includes:

- SQLite integrity check
- database identity
- art-database schema version
- artwork count
- optional expected database version

PythoFetch 1.0.0 expects:

```text
Art database schema: 1
```

When multiple compatible development databases are present, the newest compatible database version is preferred.

### Runtime Aliases

PythoFetch builds candidate artwork aliases from the detected system.

Windows candidates include values such as:

```text
Windows 11
Windows_11
Windows
```

Linux candidates can include:

```text
full PRETTY_NAME
distribution ID
version-stripped distribution name
first word of the distribution name
```

macOS candidates include:

```text
macOS
Darwin
detected macOS name
```

The database is searched by these aliases before using a family fallback.

### Artwork Variants

The primary variants are:

```text
default
small
old
```

Normal terminals prefer `default`.

Terminals narrower than the configured narrow-art threshold prefer `small` when a matching small variant exists.

`old` artwork is retained in the database for historical/reference purposes but is not automatically selected by PythoFetch 1.0.0.

## Development Art Database Recovery

When PythoFetch is run directly from Python source, the database is a development resource.

PythoFetch searches for a database:

1. beside the Python script
2. under:

```text
PythoFetchArtAssets/ArtAssetsDB
```

If no compatible database is available, the source build can retrieve the latest compatible database using:

```text
PythoFetchArtDB_Manifest.json
```

The manifest is downloaded from ProjectHomelab, and PythoFetch selects the newest entry whose database schema is compatible with the running PythoFetch version.

The database is then:

1. downloaded using the manifest `download_url`
2. checked against `size_bytes`
3. verified against `sha256`
4. validated as SQLite
5. checked for the expected PythoFetch art-database metadata

A failed verification causes the downloaded database to be rejected.

## Packaged Release Database

The downloadable art database is intended primarily for development and source execution.

Packaged PythoFetch releases bundle the art database inside the application.

For a frozen/PyInstaller build, PythoFetch looks in the application's bundled runtime directory, such as PyInstaller's `_MEIPASS` location.

A packaged release does not normally download or expose a loose `.db` file beside the executable.

If the bundled art database is missing or invalid, the release reports that PythoFetch should be reinstalled.

## User Interfaces

### ProjectHomelab TUI

Running PythoFetch with no arguments starts the ProjectHomelab terminal UI.

```text
PythoFetch
```

The TUI presents:

- ProjectHomelab / PythoFetch header
- operating-system artwork
- system information
- NeoFetch-derived color blocks
- PythoFetch version
- provider and artwork ID

The layout changes between side-by-side and stacked presentation according to available terminal width.

### Classic Mode

Classic mode presents a NeoFetch-style one-shot layout:

```text
PythoFetch --classic
```

Artwork is placed beside system information with the familiar fetch-tool layout.

### Headless Mode

Headless mode is intended for scripts, automation, other ProjectHomelab features, or applications that need PythoFetch data without an interactive interface.

```text
PythoFetch --headless
```

When no headless selector is supplied, `--all` is the effective default.

Available selectors:

```text
--info
--art
--all
```

Available formats:

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

Headless JSON writes the payload to standard output.

Headless runtime errors are written to standard error so JSON output is not contaminated by status or error text.

## Command Reference

```text
PythoFetch
```

Start the ProjectHomelab terminal UI.

```text
PythoFetch --classic
```

Print NeoFetch-style output and exit.

```text
PythoFetch --headless
```

Return the combined system-information and artwork payload in JSON.

```text
PythoFetch --headless --info
```

Return system information only.

```text
PythoFetch --headless --art
```

Return artwork only.

```text
PythoFetch --headless --all
```

Return system information and artwork.

```text
PythoFetch --headless --all --format text
```

Return plain-text output instead of JSON.

```text
PythoFetch --update
```

Check the ProjectHomelab PythoFetch release manifest and update a packaged release when a newer compatible asset is available.

```text
PythoFetch --version
```

Print the PythoFetch version.

```text
PythoFetch --help
```

Display the command-line help generated by the application.

## Argument Rules

The following combinations are intentionally rejected:

- `--classic` with `--headless`
- `--update` with display/headless modes
- `--info`, `--art`, or `--all` without `--headless`
- non-default `--format` outside headless mode

## Application Updating

PythoFetch checks:

```text
Releases/PythoFetch/PythoFetch_Release_Manifest.json
```

The release manifest identifies:

- latest application version
- available releases
- platform assets
- release package file names
- download URLs
- release-package SHA-256 checksums
- release-package file sizes
- optional explicit executable names
- optional extracted-executable SHA-256 checksums
- optional extracted-executable file sizes

A source checkout can check the manifest but does not replace the running Python source automatically.

Automatic self-replacement is intended for packaged/frozen releases.

### Release Package Formats

PythoFetch 1.0.0 supports two update payload styles:

```text
ZIP release package
direct executable / binary
```

ZIP is the preferred ProjectHomelab release format.

TAR, TAR.GZ, and TGZ update packages are not supported by PythoFetch 1.0.0.

A ZIP release must contain exactly one executable whose filename matches the executable expected for the target PythoFetch version.

The normal versioned executable names are:

```text
Windows : PythoFetch_<version>.exe
Linux   : PythoFetch_<version>
macOS   : PythoFetch_<version>
```

The manifest can override the expected executable filename with the asset-level `executable` field.

### Update Verification

The downloaded release asset is always verified against the asset-level:

```text
sha256
size_bytes
```

For a ZIP release, these values describe the ZIP itself.

A ZIP asset can additionally provide:

```text
executable_sha256
executable_size_bytes
```

These values describe the executable inside the ZIP and allow PythoFetch to verify the extracted program independently of the outer release package.

The executable checksum is optional, but using it provides an additional integrity check.

### Versioned Self-Replacement

PythoFetch executables are versioned so multiple releases do not share the same permanent filename.

For example:

```text
PythoFetch_1.0.0.exe
PythoFetch_1.0.1.exe
```

When a packaged build updates:

```text
1. PythoFetch reads the release manifest.
2. It selects the best platform and architecture asset.
3. It downloads the release package beside the running executable using a temporary update filename.
4. It verifies the package SHA-256 and size.
5. For ZIP releases, it locates exactly one expected versioned executable inside the archive.
6. It extracts that executable to a temporary update file.
7. If supplied, it verifies the extracted executable SHA-256 and size.
8. It starts an operating-system-specific handoff process.
9. The handoff waits for the current PythoFetch process to exit.
10. The new versioned executable is moved into place.
11. The previous versioned executable is removed when its filename differs from the new version.
12. The new PythoFetch executable is launched.
13. Temporary updater files are cleaned up.
```

Windows uses a temporary PowerShell handoff.

Linux and macOS use a temporary shell handoff and ensure the replacement binary is executable before launch.

### Release Manifest Asset Example

A Windows x86-64 ZIP release can be represented as:

```json
{
  "Windows_x86_64": {
    "file": "PythoFetch_1.0.0_Windows_x86_64.zip",
    "download_url": "https://raw.githubusercontent.com/Cruizepeni/ProjectHomelab/main/Releases/PythoFetch/PythoFetch_1.0.0_Windows_x86_64.zip",
    "sha256": "<release-zip-sha256>",
    "size_bytes": 12345678,
    "executable": "PythoFetch_1.0.0.exe",
    "executable_sha256": "<executable-sha256>",
    "executable_size_bytes": 16000000
  }
}
```

The checksum strings and byte counts in the example are placeholders and must be replaced with the values calculated from the actual release files.

The `sha256` and `size_bytes` fields are required by the downloader.

The `executable` field is optional when the executable follows PythoFetch's standard versioned naming convention.

The `executable_sha256` and `executable_size_bytes` fields are optional but recommended for ZIP releases.

### Platform Asset Names

PythoFetch normalizes common architecture aliases.

x86-64 aliases include:

```text
x86_64
amd64
x64
```

ARM64 aliases include:

```text
arm64
aarch64
```

Universal builds are also supported.

Typical manifest asset keys are:

```text
Windows_x86_64
Windows_arm64
Windows_Universal

Linux_x86_64
Linux_arm64
Linux_Universal

macOS_x86_64
macOS_arm64
macOS_Universal

Universal
```

Selection order is:

1. exact operating system and architecture
2. operating-system Universal build
3. generic Universal build

## Dependencies

The source version requires Python and `psutil`.

Most remaining functionality uses the Python standard library plus operating-system facilities where appropriate.

Examples include:

- PowerShell/CIM on Windows
- `/proc`, `/sys`, `lscpu`, and `lspci` where available on Linux
- `system_profiler` and `sysctl` on macOS

Packaged builds can bundle Python dependencies so the end user does not need to install Python modules manually.

## Error Handling

Normal release-mode errors are concise and user-facing.

Headless errors are written to standard error and return a non-zero exit status.

`Ctrl+C` is handled as a clean cancellation and returns exit code `130`.

## Relationship to Other ProjectHomelab Features

PythoFetch is intended to answer:

```text
What is this machine?
```

It is not intended to be a permanent live-monitoring service.

ProjectHomelab features that require continuous telemetry, history, alerts, or live graphs should consume PythoFetch where useful but keep those responsibilities in their own monitoring systems.

## Source and Artwork Structure

The development tree is expected to resemble:

```text
PythoFetch/
├── PythoFetch_1.0.0.py
└── PythoFetchArtAssets/
    ├── PythoFetchArtManager/
    │   └── PythoFetchArtManager_1.0.0.py
    ├── ArtAssetsNeofetch/
    │   ├── Windows/
    │   ├── Linux/
    │   ├── MacOS/
    │   ├── Other/
    │   └── Catalogue.json
    ├── ArtAssetsPythoFetch/
    │   ├── Windows/
    │   ├── Linux/
    │   ├── MacOS/
    │   ├── Other/
    │   └── Catalogue.json
    └── ArtAssetsDB/
        ├── PythoFetchArt_<version>.db
        └── PythoFetchArtDB_Manifest.json
```

The filesystem folder is named `MacOS` to match ProjectHomelab's folder-naming convention.

The logical family value stored in catalogue/database metadata remains:

```text
macOS
```

## Attribution and Licensing

PythoFetch should not be described as the original NeoFetch project.

It is a separate Python implementation inspired by NeoFetch and built for ProjectHomelab.

NeoFetch-origin artwork remains attributable to the NeoFetch project and its MIT license. Any substantial NeoFetch-derived material should continue to retain the required license notice.

PythoFetch-specific source and artwork should follow the licensing terms selected for ProjectHomelab.
