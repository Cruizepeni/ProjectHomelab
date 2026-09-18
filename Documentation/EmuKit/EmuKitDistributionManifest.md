# EmuKit Module Distribution Manifests

## Purpose

EmuKit uses platform manifests to advertise module packages available for one operating system.

The repository also keeps a per-module manifest as a retained version catalogue.

These files describe distribution metadata only.

They do not describe local installed state and they do not contain emulator-specific installation behavior.

## Distribution Layout

Development:

```text
SourceCode/
└── EmuKit/
    └── EmulatorModules/
        └── <OS>/
            ├── EmuKit_<OS>_Manifest.json
            └── <Module>/
                ├── <Module>_Manifest.json
                ├── <Module>_1.0.0.zip
                └── ...
```

Windows x86_64 release:

```text
Releases/
└── EmuKit/
    └── EmulatorModules/
        └── Windows/
            ├── EmuKit_Windows_Release_Manifest.json
            └── <Module>/
                ├── <Module>_Release_Manifest.json
                ├── <Module>_1.0.0_Windows_x86_64.zip
                └── ...
```


Core distribution uses a separate Core catalogue.

Development Core manifest:

```text
SourceCode/EmuKit/EmuKitCore/EmuKit_Core_Manifest.json
```

Release Core layout:

```text
Releases/
└── EmuKit/
    └── EmuKitCore/
        ├── EmuKit_Core_Release_Manifest.json
        └── EmuKit_1.0.0_Windows_x86_64.zip
```

Core release packages sit directly beside `EmuKit_Core_Release_Manifest.json`. Do not create an additional `Windows/`, `Linux/`, or `Mac/` directory below `Releases/EmuKit/EmuKitCore`; the target is expressed by the manifest target key and the target-qualified package filename.

Source/development manifests use `Name_Manifest.json`.

Release-side mirrors use `Name_Release_Manifest.json`.

Canonical `<OS>` values are:

```text
Windows
Linux
Mac
```

Release package filenames include the target operating system and architecture.

Current Windows x86_64 form:

```text
<Module>_<ModuleVersion>_Windows_x86_64.zip
```

There is no extra version directory between the module directory and the ZIP.

Correct development path:

```text
Windows/Xemu/Xemu_1.0.0.zip
```

Correct Windows x86_64 release path:

```text
Windows/Xemu/Xemu_1.0.0_Windows_x86_64.zip
```

Not:

```text
Windows/Xemu/1.0.0/Xemu_1.0.0.zip
```

## Platform Manifest

Core 1.0.0 consumes the platform manifest for runtime module discovery, download, and update decisions.

Locations:

```text
SourceCode/EmuKit/EmulatorModules/<OS>/EmuKit_<OS>_Manifest.json
Releases/EmuKit/EmulatorModules/<OS>/EmuKit_<OS>_Release_Manifest.json
```

Core selects the filename from the active channel.

Minimal schema version 1 document:

```json
{
  "SchemaVersion": 1,
  "Platform": "Windows",
  "Modules": {}
}
```

Development example:

```json
{
  "SchemaVersion": 1,
  "Platform": "Windows",
  "Modules": {
    "exampleemu": {
      "Name": "ExampleEmu",
      "Aliases": [
        "Example Emulator"
      ],
      "Version": "1.0.0",
      "Package": "ExampleEmu/ExampleEmu_1.0.0.zip",
      "SHA256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
    }
  }
}
```

Windows x86_64 release example:

```json
{
  "SchemaVersion": 1,
  "Platform": "Windows",
  "Modules": {
    "exampleemu": {
      "Name": "ExampleEmu",
      "Aliases": [
        "Example Emulator"
      ],
      "Version": "1.0.0",
      "Package": "ExampleEmu/ExampleEmu_1.0.0_Windows_x86_64.zip",
      "SHA256": "fedcba9876543210fedcba9876543210fedcba9876543210fedcba9876543210"
    }
  }
}
```

### Platform Manifest Fields

`SchemaVersion`

- required integer
- currently `1`

`Platform`

- required canonical host operating-system name
- must match the platform directory and manifest filename

`Modules`

- required object
- keys are stable module IDs

Each module entry contains:

`Name`

- human-readable module/emulator name

`Aliases`

- optional alternate lookup names

`Version`

- module package version
- must match local Info `ModuleVersion` after extraction

`Package`

- safe path relative to the current platform's `EmulatorModules/<OS>/` directory
- must not be absolute or contain `..`
- development and release package filenames may differ

`SHA256`

- lowercase SHA-256 of the exact ZIP bytes for that channel

## Per-Module Manifest

Each development module directory contains:

```text
<Module>_Manifest.json
```

The matching release directory uses:

```text
<Module>_Release_Manifest.json
```

Development example:

```json
{
  "SchemaVersion": 1,
  "Id": "exampleemu",
  "Name": "ExampleEmu",
  "Platform": "Windows",
  "Latest": "1.0.0",
  "Versions": {
    "1.0.0": {
      "Status": "supported",
      "EmulatorVersion": "4.2.0",
      "Package": "ExampleEmu_1.0.0.zip",
      "SHA256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
    }
  }
}
```

Windows x86_64 release example:

```json
{
  "SchemaVersion": 1,
  "Id": "exampleemu",
  "Name": "ExampleEmu",
  "Platform": "Windows",
  "Latest": "1.0.0",
  "Versions": {
    "1.0.0": {
      "Status": "supported",
      "EmulatorVersion": "4.2.0",
      "Package": "ExampleEmu_1.0.0_Windows_x86_64.zip",
      "SHA256": "fedcba9876543210fedcba9876543210fedcba9876543210fedcba9876543210"
    }
  }
}
```

The per-module manifest is the retained version catalogue for that module.

It records:

- stable module identity
- platform
- current latest module version
- retained module versions
- support status
- emulator version managed by each module version
- channel-specific ZIP filename
- exact channel-specific ZIP SHA-256

Core 1.0.0 does not currently need to read this file to acquire a module.

The active platform manifest remains Core's runtime index.

For the version currently advertised to Core, the platform manifest and matching per-module manifest must agree on version, package filename, and SHA-256.

## Package URL Resolution

Development:

Given:

```json
"Package": "ExampleEmu/ExampleEmu_1.0.0.zip"
```

Windows development resolves to:

```text
SourceCode/EmuKit/EmulatorModules/Windows/ExampleEmu/ExampleEmu_1.0.0.zip
```

Release:

Given:

```json
"Package": "ExampleEmu/ExampleEmu_1.0.0_Windows_x86_64.zip"
```

Windows x86_64 release resolves to:

```text
Releases/EmuKit/EmulatorModules/Windows/ExampleEmu/ExampleEmu_1.0.0_Windows_x86_64.zip
```

Absolute URLs are not required in the platform manifest.

## Package Format

Schema version 1 module packages use ZIP archives.

Development package:

```text
ExampleEmu_1.0.0.zip
└── ExampleEmu_1.0.0/
    ├── EmuKitExampleEmuInfo.json
    ├── ExampleEmuManager.py
    ├── ExampleEmuInstaller.py
    ├── ExampleEmuRepair.py
    ├── ExampleEmuUninstall.py
    └── _ExampleEmuCommon.py
```

Windows x86_64 release package:

```text
ExampleEmu_1.0.0_Windows_x86_64.zip
└── ExampleEmu_1.0.0/
    ├── EmuKitExampleEmuInfo.json
    └── ExampleEmuManager.exe
```

The development Info JSON points `Manager` at the Python manager.

The release Info JSON points `Manager` at the executable manager.

The top-level directory remains versioned because it becomes the installed local module directory under `EmuKitModules`.

Core must be able to resolve exactly one valid module root from the archive.

The compiled manager must implement the current strict JSONL executable protocol. Package naming does not change the manager protocol.

## Integrity

Core calculates SHA-256 over the downloaded ZIP before installation.

The calculated value must exactly match the active platform manifest's `SHA256`.

A mismatch aborts installation.

The same exact ZIP hash must be recorded in the corresponding per-module manifest.

Development and release packages are separate byte artifacts and normally have different hashes.

If any file inside a ZIP changes, if an executable is rebuilt, or if a ZIP is otherwise recreated with different bytes, calculate SHA-256 again and replace every manifest value that references that exact package.

Renaming a ZIP without changing its bytes does not change the SHA-256, but changing its manifest `Package` path is still required.

## Identity and Version Validation

After extraction, Core validates the module Info file.

The extracted module's stable `Id` must equal the platform manifest key.

The extracted module's `ModuleVersion` must equal the platform manifest `Version`.

Example:

```text
Platform manifest key:      exampleemu
Info Id:                    exampleemu
Platform manifest Version:  1.0.0
Info ModuleVersion:         1.0.0
```

A mismatch is rejected.

## Development Promotion

Recommended promotion flow:

```text
build canonical source/development module
→ create <Module>_1.0.0.zip
→ calculate exact development ZIP SHA-256
→ place ZIP below SourceCode/EmuKit/EmulatorModules/<OS>/<Module>/
→ update <Module>_Manifest.json
→ update EmuKit_<OS>_Manifest.json
→ remove the local development copy from EmuKitModules
→ install through the development channel
→ test source acquisition, strict lifecycle contract, progress, and emulator behavior
→ compile the manager for the target
→ create release Info JSON pointing Manager at the compiled executable
→ create target-qualified release ZIP
→ calculate exact release ZIP SHA-256
→ update <Module>_Release_Manifest.json
→ update EmuKit_<OS>_Release_Manifest.json
→ test acquisition, JSONL progress, and lifecycle behavior through the release channel
→ test the compiled module through the real compiled EmuKit release executable
→ verify emulator-only launch and game launch from the compiled Core
→ verify lifecycle child processes do not leak routine output or unwanted console windows
```

Development and release packages keep the same stable `Id`, intended `ModuleVersion`, emulator-management behavior, and system metadata.

They are not required to have the same bytes.

Each channel always records the hash of the exact package distributed by that channel.

## Publishing a New Module Version

When publishing a new module version:

1. create the new source `<Module>_<Version>.zip`
2. calculate its exact SHA-256
3. add/update the version in development `<Module>_Manifest.json`
4. update development `Latest` when appropriate
5. update the development platform manifest `Version`, `Package`, and `SHA256`
6. test through the development feed
7. compile the manager for each supported release target
8. create each target-qualified release ZIP
9. calculate each exact release ZIP SHA-256
10. add/update the version in `<Module>_Release_Manifest.json`
11. update the release platform manifest `Version`, `Package`, and `SHA256`
12. test each release target through the release channel
13. test each release target with the real compiled EmuKit executable
14. verify lifecycle child-process isolation and emulator launch behavior in the frozen Core/module path

During active development an existing module version may intentionally be rebuilt in place. In that case, do not leave a previous SHA-256 in any manifest. Recalculate and replace all affected checksums before pushing the rebuilt package.

## Core Release Rebuilds

A Core source change that affects runtime behavior does not require a Core version bump during active 1.0.0 development, but the compiled Core release package becomes a new exact byte artifact.

For a Windows x86_64 Core rebuild:

```text
build EmuKit.exe from the Core source with EmuKit.ico embedded as the Windows executable icon
→ recreate EmuKit_1.0.0_Windows_x86_64.zip
→ calculate the exact new ZIP SHA-256
→ replace the windows-x86_64 target SHA256 in EmuKit_Core_Release_Manifest.json
→ publish the new ZIP and manifest together below Releases/EmuKit/EmuKitCore/
→ test the real compiled Core against the release module feed
```

`EmuKit.ico` is the canonical Windows executable icon asset and `IconEmuKit.png` is its source artwork/reference image. They remain in the Core source tree; the compiled Windows release package only needs `EmuKit.exe` because the icon is embedded into the executable.

When Core external-process launch behavior changes, the release test must include at least one emulator-only launch and one game launch from the compiled Core. This specifically verifies that frozen-runtime DLL-search state and parent-console behavior are not leaking into the emulator process.

## Validation Checklist

Before committing module distribution metadata:

- JSON parses
- platform manifest `SchemaVersion` is supported
- platform manifest `Platform` matches its directory
- every module ID is machine-safe
- every platform entry has `Name`, `Version`, `Package`, and lowercase SHA-256
- every package path is safe and platform-feed-relative
- development package uses the source naming convention
- release package uses the target-qualified naming convention
- Core release packages sit directly below `Releases/EmuKit/EmuKitCore/` beside `EmuKit_Core_Release_Manifest.json`
- every advertised package exists
- every SHA-256 matches its exact ZIP bytes
- ZIP contains exactly one valid module root
- extracted module `Id` matches platform manifest key
- extracted module `ModuleVersion` matches platform manifest `Version`
- package is located directly under its module directory
- per-module manifest identifies the same module and platform
- current advertised version exists in the per-module `Versions` map
- platform and per-module manifests agree on package filename and SHA-256
- development Info JSON points at the source manager
- release Info JSON points at the compiled manager
- release package has been exercised through the real compiled EmuKit executable
- lifecycle child output does not corrupt JSONL or pollute the EmuKit terminal
- Core release checksum is replaced whenever the compiled Core ZIP bytes change
- rebuilt packages do not retain stale checksums

