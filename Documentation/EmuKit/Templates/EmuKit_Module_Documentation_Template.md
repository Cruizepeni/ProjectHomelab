# <Emulator Name> EmuKit Module

## Overview

Describe the upstream emulator and the role of this EmuKit module.

## Supported Systems

List systems registered by the module.

## Module Version

```text
1.0.0
```

## Pinned Emulator Version

Record the upstream emulator build currently pinned by the module.

## Upstream Resources

- Website:
- Repository:
- Wiki:
- Documentation:

## EmuKit Module Paths

Document managed emulator path, launch path, working directory, and portable data layout.

## Dependencies

Document shared Core dependencies and emulator-specific prerequisites.

## Firmware and Resources

Document required/optional BIOS, firmware, system data, and the canonical EmuKit resource-manifest paths used by the module.

## Installation

Document emulator-specific installation behavior, including any archives, executables, configuration targets, firmware, BIOS, resources, or system data users may see in progress output.

## Progress and Failure Reporting

Document any genuinely emulator-specific progress stages. Common lifecycle stages follow `EmuKit_Progress_Reporting_Standard.md`, every progress event includes a useful message, and Core presents operation-specific terminal failures such as `Install Failed` or `Repair Failed`.

## Repair

Document preserved user data and clean-reinstall behavior.

## Uninstall

Document what is removed and what is preserved.

## Known Notes

Record emulator-specific behavior that users or future maintainers need to know.
