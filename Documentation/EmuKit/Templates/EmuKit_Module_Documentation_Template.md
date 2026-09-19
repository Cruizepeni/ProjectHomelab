# <Module Name> EmuKit Module

## Purpose

Describe which emulator this module manages and the scope of the module.

## Module Identity

```text
Module ID:
Module Version:
Emulator Version:
Managed Emulator Path:
Development Manager:
Release Manager:
Lifecycle Process Name:
```

## Supported Hosts

Document each supported operating system and architecture.

## Supported Systems

List each system ID, public name, and meaningful aliases exactly as represented in the platform catalogue.

Do not document a per-system default. Catalogue `RecommendedPrimary` owns recommendation policy.

## Emulator Source

Document the upstream source, exact tested build/version, asset naming, version policy, and checksum behavior.

## Core Dependencies

Document shared Core dependencies relied upon by this module. Do not duplicate Core dependency installation inside the module.

## Controlled Resources

Record resource manifests, required paths, checksums, destinations, and generated configuration references.

## Source Layout

```text
<Module>_1.0.0/
├── EmuKit<Module>Info.json
├── <Module>Manager.py
├── <Module>Installer.py
├── <Module>Repair.py
├── <Module>Uninstall.py
└── _<Module>Common.py
```

Document intentional deviations.

## Root and Path Resolution

`.AppRoot` is the sole host marker.

The managed emulator path must resolve below:

```text
ROOT/Emulators/
```

## Installation

Describe download verification, extraction/install behavior, controlled resources, receipts, and initial configuration.

## Progress

List meaningful install/repair/update/uninstall stages reported to Core.

## Check States

Describe how the module distinguishes:

```text
missing
installed
broken
```

## Configuration

Document generated emulator configuration and managed paths.

## Repair

Describe exactly what repair restores/replaces.

## Emulator Update

Describe the emulator-version update policy implemented by the module.

The user-facing command is `Update <Emulator>`. Core owns module-package replacement before invoking module update.

## Uninstall and Data Policy

Document exactly what uninstall removes and preserves, including saves, states, screenshots, profiles, config, firmware, caches, and writable media.

## Launch Behavior

Document non-obvious launch paths, working directories, module/system launch arguments, fullscreen behavior, and `IsolateLaunchConsole` requirements.

## Lifecycle Process Behavior

Document `Lifecycle.ProcessName` when present and explain any case where the long-running process differs from `LaunchPath`.

Confirm lifecycle detection works for an emulator started manually before EmuKit.

## Lifecycle External Processes

For every external program started during install/repair/update/uninstall document why it runs, stdout/stderr handling, console isolation, diagnostic propagation, and frozen Windows DLL-search handling.

## User-Facing Completion

Record expected successful result messages and structured `details` fields.

Single-target Core operations preserve the module's own result message.

## Development Distribution

```text
SourceCode/EmuKit/EmuKitModules/<OS>/<Module>/
```

Record development package filename and exact SHA-256.

## Release Distribution

```text
Resources/EmuKit/EmuKitModules/<OS>/<Module>/
```

Record target-qualified package filename and exact SHA-256.

## Release Validation

At minimum test:

```text
check
install
repair
update
uninstall
Launch <Emulator>
game launch
Is <Emulator> Running
Close <Emulator>
Restart <Emulator>
manual-start lifecycle detection
```

## Known Constraints

Preserve upstream quirks, pinned-version reasons, compatibility constraints, and deliberate unsupported hosts.
