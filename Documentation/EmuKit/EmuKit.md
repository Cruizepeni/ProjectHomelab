# EmuKit

## Purpose

EmuKit is ProjectHomelab's emulator installation, catalogue, launch, lifecycle, and update manager.

EmuKit Core remains generic. Emulator-specific behavior belongs to emulator modules, while Core provides the shared orchestration required to discover, install, launch, close, restart, repair, update, and remove those modules consistently.

Core owns:

- `.AppRoot` root resolution and standalone fallback
- host OS and architecture detection
- shared dependency preflight
- local module discovery and registry generation
- settings and system-primary overrides
- remote platform manifest and catalogue loading
- module package download, SHA-256 verification, extraction, replacement, and removal
- catalogue-driven brand/system/emulator resolution
- emulator and game launching
- emulator process lifecycle control
- module lifecycle invocation and progress forwarding
- dependency-free terminal presentation for interactive use
- Core update discovery and handoff to the disposable Updater internal module
- migration/fresh-update cleanup
- host-specific presentation helpers such as the Windows Core folder icon

Core does not own emulator-specific download URLs, BIOS/firmware requirements, emulator configuration, emulator repair policy, emulator uninstall policy, or emulator-version update behavior. Those belong to the emulator module.

## Core 1.0.0 Source Layout

```text
SourceCode/
└── EmuKit/
    ├── EmuKitCore/
    │   ├── EmuKit_Core_Manifest.json
    │   └── EmuKit_1.0.0/
    │       ├── EmuKit.py
    │       ├── EmuKitManager.py
    │       ├── EmuKitSettings.py
    │       ├── EmuKitLauncher.py
    │       ├── EmuKitEmulatorLifecycleManager.py
    │       ├── EmuKitMigration.py
    │       ├── EmuKitPlatformIntegration.py
    │       └── EmuKitTerminalUI.py
    └── EmuKitModules/
        ├── Updater/
        │   ├── EmuKitUpdater_Manifest.json
        │   └── EmuKitUpdater_1.0.0.zip
        └── Windows/
            ├── EmuKit_Windows_Manifest.json
            ├── EmuKit_Windows_Catalogue.json
            └── <Emulator modules>/
```

The Core source is platform-neutral wherever practical. Platform-specific distribution is expressed by platform manifests and platform-specific compiled packages, not separate Core source trees.

## Root Resolution

`.AppRoot` is the sole host/root marker.

Core begins at its own runtime directory and walks upward. The nearest directory containing:

```text
.AppRoot
```

becomes `ROOT`.

If no `.AppRoot` file exists anywhere above the runtime, the Core runtime directory itself becomes `ROOT`. This is standalone mode.

There is no ProjectHomelab-specific marker, registry lookup, executable-name check, or secondary host detector.

The same rule allows a standalone EmuKit directory to be moved into another host that provides `.AppRoot`, or removed from that host and used standalone again.

## Runtime State

Core stores shared state relative to `ROOT`:

```text
ROOT/
├── Appdata/
│   ├── Cache/
│   │   └── EmuKit/
│   ├── Registry/
│   │   └── EmuKitRegistry.json
│   └── Settings/
│       └── EmuKitSettings.json
├── Dependencies/
├── Emulators/
└── ...
```

The active Core runtime has its own local module directory:

```text
<Core runtime>/EmuKitModules/
```

Installed emulator binaries remain below:

```text
ROOT/Emulators/
```

A module's `DependencyPath` must resolve to a child of `ROOT/Emulators`.

## Development and Release Feeds

Development feed base:

```text
SourceCode/EmuKit/
```

Platform development data:

```text
SourceCode/EmuKit/EmuKitModules/<OS>/
```

Release feed base:

```text
Resources/EmuKit/
```

Platform release data:

```text
Resources/EmuKit/EmuKitModules/<OS>/
```

Canonical OS names are:

```text
Windows
Linux
Mac
```

For Windows the platform files are:

```text
EmuKit_Windows_Manifest.json
EmuKit_Windows_Catalogue.json
```

for development, and:

```text
EmuKit_Windows_Release_Manifest.json
EmuKit_Windows_Catalogue.json
```

for release.

## Terminal UI and Programmatic Control

`EmuKitTerminalUI.py` is the dependency-free presentation layer for the interactive Core. It owns banners, runtime panels, tables, status markers, prompts, and progress-bar rendering. Core orchestration and emulator/module behavior remain outside the presentation layer.

The canonical frozen Windows Core is a console-subsystem executable built with PyInstaller `--console`. EmuKit does not require a separate `--noconsole` release.

Normal interactive launch displays the terminal UI. The UI enables Windows virtual-terminal support when available, uses colour only when stdout is an interactive terminal, honors the `NO_COLOR` environment variable, and falls back to uncoloured output when stdout is redirected. Presentation width is bounded so tables and panels remain readable across normal terminal sizes.

The same `EmuKit.exe` may be hosted without a visible console window by another Windows process. A controlling process may launch it with `CREATE_NO_WINDOW`, redirect stdin/stdout/stderr, send normal EmuKit CLI commands through stdin, and request raw structured command output with `--json` where supported. The controlling process is responsible for stream lifecycle and for sending `Close` when the persistent Core session should end.

Source integrations may also instantiate the `EmuKit` class directly and supply a `progress_callback` without using the terminal presentation layer.

This keeps one canonical executable capable of both polished interactive use and developer-controlled hidden execution.

## Catalogue Authority

The platform catalogue is the public authority for:

- emulator identities and aliases
- brand identities
- systems
- system aliases
- emulator-to-system relationships
- system-to-emulator relationships
- `RecommendedPrimary`

The catalogue is usable even when no emulator modules are installed locally.

Module Info JSONs still contain their own supported-system metadata because the module must be self-describing after extraction. System identity and alias data in Info JSON should mirror the platform catalogue exactly.

System aliases should represent real alternate names, regional names, or common abbreviations. Do not store formatting variants that Core normalization already handles, and do not use hardware model codes as aliases unless users genuinely identify the whole system by that code.

## Primary Emulator Model

Every catalogue system declares one `RecommendedPrimary`.

Settings store only explicit user overrides:

```json
{
  "SystemPrimaryOverrides": {
    "nintendo.n64": "ares"
  }
}
```

Resolution is:

```text
user override, if present
otherwise catalogue RecommendedPrimary
```

Core does not silently select an arbitrary installed alternative when the resolved primary is unavailable.

Public commands are:

```text
Set <Emulator> as <System> Primary
Restore <System> Primary
Restore Systems Primary
```

`Restore` removes overrides; it does not install software.

## Module Info and Local Discovery

A valid local emulator module contains one `EmuKit*Info.json` file and the manager entry point named by that Info file.

Typical source module:

```text
ExampleEmu_1.0.0/
├── EmuKitExampleEmuInfo.json
├── ExampleEmuManager.py
├── ExampleEmuInstaller.py
├── ExampleEmuRepair.py
├── ExampleEmuUninstall.py
└── _ExampleEmuCommon.py
```

Typical Windows release module:

```text
ExampleEmu_1.0.0/
├── EmuKitExampleEmuInfo.json
└── ExampleEmuManager.exe
```

The local module directory answers what module code is physically installed. The registry records what Core successfully discovered and normalized. The remote platform manifest records what packages may be downloaded. These authorities are deliberately separate.

## Emulator Lifecycle Metadata

Module Info may declare:

```json
"Lifecycle": {
  "ProcessName": "ExampleEmu.exe"
}
```

Core uses lifecycle metadata together with the resolved `LaunchPath` to identify running emulator processes.

Lifecycle control must not depend on Core having launched the emulator. A user may manually start an emulator before EmuKit and still use:

```text
Is <Emulator> Running
Close <Emulator>
Restart <Emulator>
```

System forms resolve the current primary emulator:

```text
Is <System> Running
Close <System>
Restart <System>
```

`Get Running Emulators` reports known running emulator modules.

## Launch Model

Public launch forms are:

```text
Launch <Emulator>
Launch <GamePath> <System>
Launch <Emulator> <GamePath> <System>
```

`Launch <Emulator>` opens the emulator without a game.

`Launch <GamePath> <System>` resolves the system's primary emulator.

The explicit emulator form bypasses primary selection but Core verifies that the requested emulator supports the requested system.

System parsing supports multiword names and brand-qualified names. Resolver normalization is case-insensitive and tolerates common punctuation, spacing, underscore, and hyphen variations.

## Core Dependencies

Core 1.0.0 currently preflights:

```text
7-Zip 26.03
  Windows: required
  Linux: required
  Mac: required

Microsoft Visual C++ v14 Redistributable
  Windows: required
```

Shared dependency acquisition belongs to Core. Emulator modules should not independently reinstall shared Core dependencies.

## Module Operations

Public module operations are:

```text
Install <Emulator(s)>
Install All
Uninstall <Emulator(s)>
Uninstall All
Repair <Emulator(s)>
Remove <Emulator(s)>
Update <Emulator(s)>
```

`Remove` removes the EmuKit module package only. It does not uninstall the emulator managed by that module.

`Update <Emulator>` is the complete user-facing emulator update operation. Core first updates the EmuKit module package when a newer module exists, then invokes that module's `update` lifecycle operation so the module can update the emulator version it owns.

A single-target operation preserves the module's specific result message. Multi-target operations may produce an aggregate summary.

## Catalogue and Info Commands

```text
Get Catalogue
Get System Catalogue
Get Emulator Catalogue
Get <Brand|System|Emulator> Info
Get Current Installs
Get Running Emulators
Get Settings
```

`Get Catalogue` is the high-level catalogue summary.

`Get System Catalogue` lists supported systems grouped by brand.

`Get Emulator Catalogue` lists supported emulator modules.

Detailed system information presents the public primary state as `Primary Emulator`, `Primary Source`, and installation availability rather than exposing internal resolver terminology.

Both `Catalog` and `Catalogue` spellings are accepted for catalogue commands.

## CLI Reference

```text
Get Catalogue
Get System Catalogue
Get Emulator Catalogue
Get Settings
Get Running Emulators
Get Current Installs
Get <Brand|System|Emulator> Info

Set Feature Fullscreen True|False
Set <Emulator> as <System> Primary
Restore <System> Primary
Restore Systems Primary

Launch <Emulator>
Launch <GamePath> <System>
Launch <Emulator> <GamePath> <System>

Close <Emulator|System>
Restart <Emulator|System>
Is <Emulator|System> Running

Install <Emulator(s)>
Install All
Uninstall <Emulator(s)>
Uninstall All
Repair <Emulator(s)>
Remove <Emulator(s)>
Update <Emulator(s)>

Updates
Check Updates
Check for Updates
Get Updates
Update EmuKit

Help
Close
```

`Close` by itself exits EmuKit.

`--json` requests raw structured output and `--verbose` requests additional operation detail where supported.

Obsolete pre-1.0 command vocabulary such as `Assign System`, `Launch Emulator`, `Update Module`, `Refresh Modules`, and `Get Supported Systems` is not part of the public 1.0.0 CLI.

## Core Updates

Core release metadata lives at:

```text
Releases/EmuKit/EmuKit_Core_Release_Manifest.json
```

Target-qualified Core packages live beside that manifest, for example:

```text
Releases/EmuKit/EmuKit_1.0.0_Windows_x86_64.zip
```

A Core release descriptor supplies:

- `OS`
- `Architecture`
- `Package`
- `SHA256`
- `RootDirectory`
- `Executable`

The disposable Updater is not bundled permanently into Core. It is published as an internal module in the platform release feed. See `EmuKitUpdater.md`.

## Core Update Flow

```text
Update EmuKit
→ check EmuKit_Core_Release_Manifest.json
→ identify target package
→ load the release platform manifest
→ locate InternalModules.updater
→ download and verify the Core ZIP
→ download and verify the Updater ZIP
→ safely extract the Updater
→ launch the Updater with handoff arguments
→ Core exits
→ Updater replaces Core and launches the new Core
→ new Core migrates/validates
→ new Core removes updater/staging/old backup after successful handoff
```

The Updater is disposable and is never treated as an emulator in the public catalogue.

## Windows Core Folder Icon

Frozen Windows Core builds apply their own embedded executable icon to the versioned Core folder.

Core creates:

```text
EmuKit_1.0.0/
├── EmuKit.exe
└── desktop.ini
```

with an Explorer shell entry equivalent to:

```ini
[.ShellClassInfo]
IconResource=EmuKit.exe,0
```

Core marks `desktop.ini` hidden/system and applies the Windows folder customization attribute. The Updater applies the same identity after installing a new Core.

Linux and Mac treat this integration as not applicable.

The release package therefore does not need to ship a separate icon file solely for the folder icon; Windows uses the icon embedded in `EmuKit.exe`.

## Frozen Runtime Boundary

Core must prevent PyInstaller runtime state from leaking into external emulator processes or module lifecycle child processes.

Core owns the launch boundary for normal emulator launches. Modules own every external process they start during install, repair, update, or uninstall.

Compiled release validation must include emulator-only launch, game launch, lifecycle operations, and manually started emulator process detection.

## Release Acceptance

Before considering a Core build releasable, verify at minimum:

```text
standalone mode without .AppRoot
hosted mode with .AppRoot
online development feed
online release feed
offline cached catalogue behavior
catalogue and Info lookup
system aliases and brand-qualified resolution
primary override and restore
all three Launch forms
manual and Core-started lifecycle detection
Close / Restart / Is Running / Get Running Emulators
Install / Repair / Update / Uninstall / Remove
batch operations
Core update handoff
fresh-update migration and cleanup
terminal UI startup, tables, prompts, and progress rendering
redirected/no-window Core control using the same console-subsystem executable
Windows folder identity on frozen builds
```
