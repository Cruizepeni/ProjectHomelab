# EmuKit Emulator Module Contract

## Purpose

An EmuKit emulator module is the adapter between generic EmuKit Core behavior and one emulator project's specific installation and lifecycle behavior.

Core must not contain emulator-specific installation knowledge.

A compliant module declares:

- stable module identity
- module version
- pinned emulator version
- human-readable description
- public help and project links
- manager entry point
- managed emulator install and launch locations
- supported systems
- lifecycle process identity when needed
- upstream source metadata
- license metadata
- host support
- dependencies and resources
- data and repair policy

and implements:

```text
check
install
uninstall
repair
update
```

## Package Layout

Development package root:

```text
ExampleEmu_1.0.0/
├── EmuKitExampleEmuInfo.json
├── ExampleEmuManager.py
├── ExampleEmuInstaller.py
├── ExampleEmuRepair.py
├── ExampleEmuUninstall.py
└── _ExampleEmuCommon.py
```

Typical compiled Windows release package root:

```text
ExampleEmu_1.0.0/
├── EmuKitExampleEmuInfo.json
└── ExampleEmuManager.exe
```

Core discovers exactly one `EmuKit*Info.json` registration per module root.

## Source Cleanliness

Committed module Python source must contain:

```text
0 comments
0 docstrings
0 __pycache__ directories
0 .pyc files
0 .pyo files
```

Temporary build output must not be packaged.

## Root Resolution

`.AppRoot` is the sole host marker.

Module source begins at its own directory and searches upward for `.AppRoot`.

If no marker exists and the module is located below an EmuKit runtime `EmuKitModules` directory, the runtime becomes the standalone root.

Do not introduce alternate ProjectHomelab-specific root detectors.

## Module Version vs Emulator Version

These are separate identities.

```text
ModuleVersion
```

identifies the EmuKit module package revision.

```text
EmulatorVersion
```

identifies the upstream emulator build pinned by that module package.

All current first-generation modules remain `ModuleVersion: 1.0.0` until a post-1.0.0 module revision is intentionally released.

## Core-Validated Registration Fields

Schema version 1 requires at least:

```json
{
  "Version": 1,
  "Id": "exampleemu",
  "Name": "ExampleEmu",
  "Aliases": [],
  "Manager": "ExampleEmuManager.py",
  "DependencyPath": "Emulators/ExampleEmu",
  "LaunchPath": "Emulators/ExampleEmu/example.exe",
  "Systems": {}
}
```

The 1.0.0 public module contract additionally requires modules to provide `ModuleVersion`, `EmulatorVersion`, `Description`, and `Links`.

## Description

`Description` is a concise user-facing description of the emulator project and its purpose.

It should explain what the emulator is, not how EmuKit installs it.

## Links

Every public module Info JSON should provide the same user-facing link object:

```json
"Links": {
  "Website": "https://example.invalid/",
  "Repository": "https://github.com/example/example",
  "Wiki": null,
  "Documentation": "https://example.invalid/docs",
  "EmuKitModuleDocumentation": "https://github.com/Cruizepeni/ProjectHomelab/blob/main/Documentation/EmuKit/Modules/ExampleEmu_Module.md"
}
```

Fields are:

- `Website`: upstream project website when one exists
- `Repository`: upstream source repository
- `Wiki`: upstream wiki when one exists
- `Documentation`: upstream emulator documentation
- `EmuKitModuleDocumentation`: ProjectHomelab documentation for this EmuKit module

Use `null` when an upstream resource genuinely does not exist.

`Issues` is not part of the standard public Links contract.

`Source` metadata and `Links` may contain some overlapping URLs. This is intentional: `Source` is installation provenance; `Links` is user-facing help/discovery metadata.

## Module Documentation Paths

Current module documentation filenames are based on the stable EmuKit module name:

```text
Documentation/EmuKit/Modules/Ares_Module.md
Documentation/EmuKit/Modules/MGBA_Module.md
Documentation/EmuKit/Modules/Xemu_Module.md
Documentation/EmuKit/Modules/Xenia_Module.md
Documentation/EmuKit/Modules/YabaSanshiro2_Module.md
```

Initial placeholder files may contain only:

```text
Coming Soon
```

## Lifecycle Metadata

A module may declare:

```json
"Lifecycle": {
  "ProcessName": "ExampleEmu.exe"
}
```

Core also derives process identity from `LaunchPath`.

Lifecycle commands must work even if the emulator was started manually rather than by EmuKit.

## Paths

`DependencyPath`, `LaunchPath`, and `WorkingDirectory` are relative to resolved `ROOT`.

Managed emulator trees belong below:

```text
ROOT/Emulators/<Emulator>
```

`DependencyPath` must identify a child of `ROOT/Emulators`.

## Host Support

Module Info should explicitly describe platform support:

```json
"HostSupport": {
  "Windows": {
    "Supported": true,
    "Architectures": ["x86_64"]
  },
  "Linux": {
    "Supported": false
  },
  "Mac": {
    "Supported": false
  }
}
```

A platform-specific module package only advertises the host targets it actually supports.

## Requirements

Requirements describe shared dependencies and firmware expectations without moving emulator-specific behavior into Core.

Example:

```json
"Requirements": {
  "CoreDependencies": ["7zip"],
  "BIOSRequired": false
}
```

Current shared Core dependency IDs include:

```text
7zip
vcredist
```

## Systems

Example:

```json
"Systems": {
  "example.exampleconsole": {
    "Name": "Example Console",
    "Aliases": ["EC"],
    "Brand": {
      "Id": "example",
      "Name": "Example",
      "Aliases": []
    },
    "Platform": {
      "Id": "console",
      "Name": "Console",
      "Aliases": []
    },
    "LaunchArguments": [
      "{fullscreen}",
      "{game}"
    ],
    "FullscreenArgument": "--fullscreen",
    "SupportedExtensions": [".example"]
  }
}
```

A system registration provides:

- stable system ID
- `Name`
- `Aliases`
- `Brand`
- `Platform`
- `LaunchArguments`

Optional fields include:

- `LaunchPath`
- `WorkingDirectory`
- `FullscreenArgument`
- `IsolateLaunchConsole`
- `SupportedExtensions`
- `Notes`
- firmware/resource references owned by the module implementation

Do not use a per-system `Default` field. Recommended primary belongs to the platform catalogue.

## Catalogue Consistency

For each module system:

- the same system ID exists in the platform catalogue
- public system name and aliases match
- the catalogue emulator record lists the system
- the catalogue system record lists the emulator

System support changes normally require rebuilding the module package, updating the platform catalogue, recalculating the module package SHA-256, recalculating the catalogue SHA-256, and updating affected manifests.

## Source Metadata

`Source` records exact installation provenance.

Example:

```json
"Source": {
  "Type": "PinnedRelease",
  "Provider": "GitHub",
  "Repository": "owner/repository",
  "ReleaseTag": "v4.2.0",
  "ReleaseCommit": "abcdef0",
  "Asset": "example.zip",
  "DownloadURL": "https://example.invalid/example.zip",
  "Size": 123456,
  "SHA256": "replace-with-upstream-sha256"
}
```

Use the cleanest useful `EmulatorVersion` for display while retaining the exact upstream release/tag/commit identity in `Source`.

## License Metadata

Example:

```json
"License": {
  "Name": "GPL-3.0",
  "Url": "https://example.invalid/LICENSE",
  "Distribution": "EmuKit downloads the official upstream release."
}
```

## Resource Catalogue

ProjectHomelab-controlled BIOS, firmware, or other emulator resources are acquired through the central EmuKit resource catalogue when appropriate.

Example:

```json
"ResourceCatalog": {
  "ManifestURL": "https://raw.githubusercontent.com/Cruizepeni/ProjectHomelab/main/Resources/EmuKit/EmuKit_Resources_Manifest.json",
  "RawBaseURL": "https://raw.githubusercontent.com/Cruizepeni/ProjectHomelab/main/Resources/EmuKit"
}
```

Resource paths, sizes, MD5 values, and SHA-256 values used by modules must match the canonical resource manifest.

## Data Policy

Example:

```json
"DataPolicy": {
  "ManagedEmulatorPath": "Emulators/ExampleEmu",
  "ResourcesInstalledInsideEmulator": true,
  "UninstallRemovesManagedEmulatorTree": true,
  "PortableMode": true,
  "RepairPreserves": [
    "config",
    "saves"
  ]
}
```

The module implementation remains the final authority for actual preservation behavior.

## Manager Protocol

Core invokes:

```text
<Manager> <check|install|uninstall|repair|update> --json
```

The manager writes JSONL to stdout.

Progress record:

```json
{"type":"progress","percent":25,"stage":"Downloading Emulator","message":"example.zip"}
```

Final record:

```json
{"type":"result","result":{"success":true,"module":"exampleemu","operation":"install","state":"installed","message":"ExampleEmu Version 4.2.0 installed successfully.","details":null}}
```

Module source must not write unrelated text to stdout in JSON mode.

## Check

`check` reports real managed emulator state and distinguishes at least:

```text
missing
installed
broken
```

It may validate:

- executable presence
- expected version
- install receipt
- executable checksum
- required firmware/resources
- critical portable configuration

## Install

`install` owns emulator-specific acquisition and initial configuration.

Typical responsibilities are:

- validate host support
- download exact pinned bytes
- validate size/checksum/archive integrity
- extract/install into `ROOT/Emulators/<Module>`
- establish portable configuration when supported
- acquire and validate required controlled resources
- fingerprint installed executable
- write `.emukit_install.json`
- verify final managed state

An installer should still reject an already-existing managed install tree as a safety guard. Core `Install <Emulator>` and `Install All` both check module state first and avoid invalid install requests.

## Repair

Repair owns emulator-specific reinstall and preservation policy.

Where user data is stored inside the managed emulator tree, move preserved state outside the tree before clean uninstall/reinstall, then restore it afterward.

Recovery data should use:

```text
ROOT/Appdata/Cache/EmuKit/<Module>/
```

when manual recovery may be necessary.

## Uninstall

Uninstall follows the module's explicit Data Policy.

`Uninstall` removes emulator application state according to module policy.

It is different from Core `Remove`, which removes the local EmuKit module package without uninstalling the emulator application.

## Update

`update` manages the emulator version pinned by the current module package.

A common implementation is:

- run `check`
- return `already_current` if valid/current
- otherwise use repair/reinstall logic to restore the module-pinned emulator build

Core/module package updates are separate from emulator lifecycle updates.

## Progress Language

All modules use the canonical progress vocabulary in `EmuKit_Progress_Reporting_Standard.md`.

Every emitted module progress event must include a meaningful `message`.

When the operation handles a concrete file, archive, executable, directory, receipt, configuration file, BIOS, firmware image, resource, or system-data file, the message identifies that target.

Examples:

```text
Downloading Emulator      exampleemu-4.2.0.zip
Validating Emulator       exampleemu-4.2.0.zip
Installing Emulator       exampleemu.exe
Checking Receipt          .emukit_install.json
Downloading Resources     bios.bin
Removing Emulator         Emulators/ExampleEmu
```

Do not use stage-only progress events when a useful target is known.

Variation in stage names is allowed only when the operation genuinely performs emulator-specific work such as firmware/resource/system-data acquisition.

## Completion and Failure Contract

Modules explicitly emit lifecycle completion stages such as:

```text
Install Complete
Check Complete
Repair Complete
Uninstall Complete
```

with a useful completion message such as the pinned version or managed path.

Core owns the final terminal presentation. Module-level `100%` completion is treated as provisional while Core waits for the final lifecycle result.

A successful final result allows Core to present `Installed`, `Repaired`, `Updated`, or `Uninstalled`.

Failures converge on operation-specific terminal stages:

```text
Check Failed
Install Failed
Uninstall Failed
Repair Failed
Update Failed
```

This applies to explicit module failures, pre-operation failures, unexpected states, and unhandled module exceptions.

A module must not rely on a prior `Install Complete` or equivalent progress event as proof of success. The final result record is authoritative.
