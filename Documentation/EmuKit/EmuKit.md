# EmuKit

## Purpose

EmuKit is ProjectHomelab's emulator catalogue, installation, launch, lifecycle, module, and update manager.

EmuKit 1.0.0 is built around a strict split of responsibility:

- Core owns generic orchestration.
- Emulator modules own emulator-specific behavior.
- The platform catalogue owns public brand, system, emulator, relationship, alias, and recommended-primary metadata.
- Module Info JSON owns the technical identity and implementation contract for one emulator module.
- Local state answers what module packages and emulator applications are actually present on the current machine.

## Core Responsibilities

Core owns:

- `.AppRoot` root resolution and standalone fallback
- host OS and architecture detection
- shared dependency preflight
- local module discovery and registry generation
- settings and system-primary overrides
- remote platform manifest and catalogue loading
- module package acquisition, SHA-256 verification, extraction, replacement, and removal
- catalogue-driven brand, system, and emulator resolution
- installed-emulator and installed-module state reporting
- emulator and game launching
- emulator process lifecycle control
- module lifecycle invocation and progress forwarding
- `Install All`, `Uninstall All`, and `Remove All` orchestration
- dependency-free terminal presentation
- Core update discovery and handoff to the internal Updater module
- migration and fresh-update cleanup
- host-specific presentation helpers such as the Windows Core folder icon

Core does not own emulator-specific download URLs, archive formats, BIOS or firmware rules, emulator configuration, emulator repair policy, emulator uninstall policy, or emulator-version update logic. Those belong to the emulator module.

## Current Windows Module Set

EmuKit 1.0.0 currently has 18 Windows emulator modules:

- Ares
- Azahar
- Cemu
- DuckStation
- Flycast
- Gopher64
- Mednafen
- MelonDS
- MesenCE
- MGBA
- PCSX2
- PPSSPP
- RPCS3
- SameBoy
- Vita3K
- Xemu
- Xenia Canary
- Yaba Sanshiro 2

Exact emulator versions are intentionally stored in module Info JSON and distribution manifests rather than duplicated here.

## Core Source Layout

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
        └── Windows/
```

## Root Resolution

`.AppRoot` is the sole root marker.

Core starts at its runtime directory and walks upward. The nearest directory containing:

```text
.AppRoot
```

becomes `ROOT`.

If no `.AppRoot` exists above the Core runtime, the runtime directory itself becomes `ROOT`. This is standalone mode.

No ProjectHomelab-specific secondary marker, registry lookup, executable-name heuristic, or alternate host detector is part of the 1.0.0 contract.

## Runtime State

Shared state is stored relative to `ROOT`:

```text
ROOT/
├── Appdata/
│   ├── Cache/
│   │   └── EmuKit/
│   ├── Registry/
│   │   └── EmuKitRegistry.json
│   └── Settings/
│       └── EmuKitSettingsConfig.json
├── Dependencies/
├── Emulators/
└── ...
```

The active Core runtime owns the local module directory:

```text
<EmuKit runtime>/EmuKitModules/
```

Emulator applications managed by modules live below:

```text
ROOT/Emulators/
```

## Development and Release Feeds

Development feed:

```text
SourceCode/EmuKit/
```

Development platform data:

```text
SourceCode/EmuKit/EmuKitModules/<OS>/
```

Release feed:

```text
Resources/EmuKit/
```

Release platform data:

```text
Resources/EmuKit/EmuKitModules/<OS>/
```

Canonical OS values are:

```text
Windows
Linux
Mac
```

## Catalogue, Info, and Local State

EmuKit deliberately separates three concepts.

### Catalogue

Catalogue commands answer what exists and how entities relate.

```text
Get Catalogue
Get Brand Catalogue
Get System Catalogue
Get Emulator Catalogue
Get <Brand> Catalogue
Get <System> Catalogue
Get <Emulator> Catalogue
```

Examples:

```text
Get Nintendo Catalogue
Get Game Boy Advance Catalogue
Get MesenCE Catalogue
```

### Info

Info commands answer everything EmuKit currently knows about one entity.

```text
Get <Brand> Info
Get <System> Info
Get <Emulator> Info
```

Emulator Info is designed to include description, version information, host support, source metadata, license, supported systems, and user-facing links supplied by the module Info JSON.

### Local State

Local-state commands answer what exists on the current machine.

```text
Get Current Installs
Get Installed Emulators

Get Current Modules
Get Installed Modules

Get Running Emulators
```

`Get Current Installs` and `Get Installed Emulators` are equivalent.

`Get Current Modules` and `Get Installed Modules` are equivalent.

An emulator application and its EmuKit module package are intentionally different states. Removing a module package does not mean the emulator application was uninstalled.

## Install Preflight and Install All

Install preflight is Core orchestration.

Both:

```text
Install <Emulator>
Install All
```

use the same state gate.

For each requested emulator Core:

1. ensures the module package is available locally
2. invokes the module's generic `check`
3. skips installation when state is `installed`
4. invokes `install` only when state is `missing`
5. does not overwrite state `broken`; Repair is required
6. reports unexpected check states and acquisition/check failures as install failures

This does not move emulator-specific install knowledge into Core. Core only decides whether a generic lifecycle operation should be requested; the module still owns how that operation works.

For an install that must first acquire its module package, Core presents module acquisition and emulator installation as one continuous terminal operation rather than two completed lines.

The integrated install progress range is:

```text
0-20%    Module acquisition
20-99%   Emulator lifecycle
100%     Core-authoritative Installed result
```

Module acquisition progress is scaled into the first portion of the line. Once the module package is available, the module's emulator lifecycle reuses that same line and is scaled into the remaining provisional range. Core finalizes the line only after a successful lifecycle result.

A module-acquisition failure terminates the same line as `Install Failed`.

Standalone module-package acquisition, when performed independently of emulator installation, remains its own normal `0-100%` operation.

## Remove vs Uninstall

```text
Uninstall <Emulator>
Uninstall All
```

remove emulator applications through module lifecycle logic.

```text
Remove <Emulator>
Remove All
```

remove local EmuKit module packages while leaving emulator applications untouched.

## Terminal UI and Programmatic Control

`EmuKitTerminalUI.py` is presentation only. It owns panels, tables, progress bars, status markers, prompts, and interactive command presentation.

Core orchestration and module logic do not belong in the UI layer.

Module progress uses canonical stages plus a meaningful message identifying the file, path, resource, version, configuration target, receipt, or other concrete object being handled.

Core reserves the final displayed `100%` for the authoritative lifecycle result. A module-reported completion event is forwarded as provisional progress, then Core finishes the line only after the module result is known.

Successful terminal lifecycle states include:

```text
Installed
Repaired
Updated
Uninstalled
```

Operation-specific failure states include:

```text
Check Failed
Install Failed
Repair Failed
Update Failed
Uninstall Failed
```

Any stage ending in `Failed` is terminal and cannot be overwritten by the next module's progress.

The canonical Windows Core is a console-subsystem executable. Another process may launch it without a visible console by using Windows process flags and redirected standard streams. Machine-readable command output is available through `--json` where supported.

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
user override, when present
otherwise catalogue RecommendedPrimary
```

Core does not silently select an arbitrary installed alternative when the resolved primary is unavailable.

Commands are:

```text
Set <Emulator> as <System> Primary
Restore <System> Primary
Restore Systems Primary
```

## Coding Cleanliness

Committed EmuKit Core and emulator-module Python source must not contain:

- Python comments
- Python docstrings
- `__pycache__`
- `.pyc`
- `.pyo`

Build and temporary output also stays outside committed module source packages.

## Related Documentation

- `EmuKit_Command_Reference.md`
- `EmuKit_Catalogue_Contract.md`
- `EmuKit_Module_Contract.md`
- `EmuKit_Progress_Reporting_Standard.md`
- `EmuKit_Distribution_Manifest.md`
- `EmuKit_Updater.md`
