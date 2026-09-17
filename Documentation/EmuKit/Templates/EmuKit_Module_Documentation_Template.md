# <Module Name> EmuKit Module

## Purpose

Describe which emulator this module manages and why the module exists.

## Module Identity

```text
Module ID:
Module Version:
Emulator Version:
Managed Emulator Path:
```

The managed emulator path should normally be below:

```text
ROOT/Emulators/
```

## Supported Systems

List each system declared by the module and any meaningful compatibility limitations.

## Emulator Source

Document the upstream emulator source and the version policy used by this module.

## Controlled Resources

Describe any ProjectHomelab Resources consumed by the module.

Record how those resources are mapped into the emulator's installed layout.

## Installation

Describe meaningful module-specific installation behavior.

## Check States

Describe how the module distinguishes:

```text
missing
installed
broken
```

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

Document non-obvious launch arguments, fullscreen behavior, or per-system differences.

## Distribution

Record the module package naming convention and any important distribution constraints.

The development package should be tested through `backend/EmuKit` before the exact bytes are promoted to `Releases/EmuKit`.

## Known Constraints

Preserve upstream quirks, pinned-version reasons, or compatibility constraints that future maintainers need to know.
