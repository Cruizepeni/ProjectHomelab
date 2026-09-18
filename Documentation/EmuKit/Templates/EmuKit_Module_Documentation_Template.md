# <Module Name> EmuKit Module

## Purpose

Describe which emulator this module manages and why the module exists.

## Module Identity

```text
Module ID:
Module Version:
Emulator Version:
Managed Emulator Path:
Development Manager:
Release Manager:
```

The managed emulator path should be below:

```text
ROOT/Emulators/
```

## Supported Hosts

Document each supported operating system and architecture.

## Supported Systems

List each system declared by the module and any meaningful compatibility limitations.

## Emulator Source

Document the upstream emulator source, exact tested version/build, asset naming, version policy, and pinned checksum behavior.

If upstream uses a rolling release, document how the module prevents changed upstream bytes from silently replacing the tested build.

## Core Dependencies

Document which shared Core dependencies the module relies on.

Do not duplicate shared Core dependency installation inside the module.

## Controlled Resources

Describe any ProjectHomelab Resources consumed by the module.

Record:

- resource manifest used
- required resource paths
- checksum requirements
- install destinations
- configuration references

## Source Layout

Record the module source files and any intentional deviations from:

```text
<Module>_1.0.0/
├── EmuKit<Module>Info.json
├── <Module>Manager.py
├── <Module>Installer.py
├── <Module>Repair.py
├── <Module>Uninstall.py
└── _<Module>Common.py
```

## Root and Path Resolution

Document unusual path behavior if any.

Compiled managers must use frozen-safe module-directory resolution.

`.ProjectHomelabRoot` remains the only ProjectHomelab root marker.

## Installation

Describe meaningful module-specific installation behavior.

Include download verification, extraction/installer behavior, resource placement, receipts, portable-mode behavior, and initial configuration where applicable.

## Progress

Describe the meaningful install/repair/update/uninstall stages reported to Core.

The release manager uses strict JSONL progress/result stdout.

## Check States

Describe how the module distinguishes:

```text
missing
installed
broken
```

List the files, receipts, versions, checksums, configuration, and resources that are validated.

## Configuration

Document module-generated emulator configuration and any paths the module writes into that configuration.

## Repair

Describe what repair restores.

State whether repair replaces configuration, emulator binaries, writable images, or other managed state.

## Emulator Update

Describe the emulator-update policy.

Module-package update behavior belongs to EmuKit Core.

## Uninstall and Data Policy

Document exactly what the module removes and what it preserves.

Consider:

- saves
- states
- screenshots
- controller profiles
- configuration
- user-supplied firmware/BIOS
- caches
- writable disk images or equivalent emulator state

## Launch Behavior

Document non-obvious launch arguments, fullscreen behavior, working directory behavior, or per-system differences.

Record whether module-level or system-level `IsolateLaunchConsole` is required and why. Leave it disabled when the emulator behaves correctly with normal Core launching.

## Lifecycle External Processes

Document every external tool started during install, repair, update, or uninstall.

For each one record:

- why it is launched
- whether stdout/stderr is captured or redirected
- whether console isolation is required
- how failures return diagnostic output through structured `details`
- whether frozen Windows DLL-search sanitization is required

Source and compiled-manager lifecycle behavior should remain equivalent.

## Development Distribution

Record:

```text
<Module>_1.0.0.zip
```

and its development manifest locations.

The development ZIP is hashed independently.

## Release Distribution

For Windows x86_64 record:

```text
<Module>_1.0.0_Windows_x86_64.zip
```

and its release manifest locations.

The release Info JSON points at the compiled `.exe` manager.

The release ZIP is hashed independently from the development ZIP.

## Release Validation

Record the results of testing the actual compiled module through the actual compiled EmuKit release executable.

At minimum cover:

```text
check
install
repair
update
uninstall
Launch Emulator
game launch
```

Confirm that lifecycle subprocesses do not leak routine output into EmuKit, no unwanted child console windows appear, and emulator launches do not inherit PyInstaller runtime DLLs.

## Known Constraints

Preserve upstream quirks, pinned-version reasons, compatibility constraints, and deliberate unsupported hosts that future maintainers need to know.
