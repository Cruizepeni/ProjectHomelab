# EmuKit Module Distribution Manifests

## Purpose

EmuKit uses platform manifests to advertise module packages available for one operating system.

The repository also keeps a per-module manifest as a retained version catalogue.

These files describe distribution metadata only.

They do not describe local installed state and they do not contain emulator-specific installation behavior.

## Distribution Layout

Development:

```text
backend/
└── EmuKit/
    └── EmulatorModules/
        └── <OS>/
            ├── EmuKit_<OS>_Manifest.json
            └── <Module>/
                ├── <Module>_Manifest.json
                ├── <Module>_1.0.0.zip
                ├── <Module>_1.0.1.zip
                └── ...
```

Release uses the same package hierarchy with release-specific manifest names:

```text
Releases/
└── EmuKit/
    └── EmulatorModules/
        └── <OS>/
            ├── EmuKit_<OS>_Release_Manifest.json
            └── <Module>/
                ├── <Module>_Release_Manifest.json
                ├── <Module>_1.0.0.zip
                ├── <Module>_1.0.1.zip
                └── ...
```

Backend/source manifests use `Name_Manifest.json`. Release-side mirrors use `Name_Release_Manifest.json`.

Canonical `<OS>` values are:

```text
Windows
Linux
Mac
```

There is no extra version directory between the module directory and the ZIP.

Correct:

```text
Windows/Xemu/Xemu_1.0.0.zip
```

Not:

```text
Windows/Xemu/1.0.0/Xemu_1.0.0.zip
```

## Platform Manifest

Core 1.0.0 consumes the platform manifest for runtime module discovery, download, and update decisions.

Locations:

```text
backend/EmuKit/EmulatorModules/<OS>/EmuKit_<OS>_Manifest.json
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

Populated example:

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

`SHA256`

- lowercase SHA-256 of the exact ZIP bytes

## Per-Module Manifest

Each backend module directory may contain:

```text
<Module>_Manifest.json
```

The matching release directory uses:

```text
<Module>_Release_Manifest.json
```

Current repository convention:

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

The per-module manifest is the retained version catalogue for that module.

It records:

- stable module identity
- platform
- current latest module version
- retained module versions
- support status
- emulator version managed by each module version
- ZIP filename
- ZIP SHA-256

Core 1.0.0 does not currently need to read this file to acquire a module.

The active platform manifest remains Core's runtime index.

The platform manifest and per-module manifest must agree on the package version, filename, and SHA-256 for the version currently advertised to Core.

## Package URL Resolution

Given:

```json
"Package": "ExampleEmu/ExampleEmu_1.0.0.zip"
```

Windows development resolves to:

```text
backend/EmuKit/EmulatorModules/Windows/ExampleEmu/ExampleEmu_1.0.0.zip
```

Windows release resolves to:

```text
Releases/EmuKit/EmulatorModules/Windows/ExampleEmu/ExampleEmu_1.0.0.zip
```

Absolute URLs are not required in the manifest.

## Package Format

Schema version 1 module packages use ZIP archives.

The recommended package shape is:

```text
ExampleEmu_1.0.0.zip
└── ExampleEmu_1.0.0/
    ├── EmuKitExampleEmuInfo.json
    ├── ExampleEmuManager.py
    └── module-owned supporting files
```

Development packages commonly contain a Python manager. A release package may instead contain a compiled executable manager plus the external `EmuKit*Info.json` that points `Manager` at that executable.

The top-level directory is versioned because it becomes the installed local module directory under `EmuKitModules`.

Core must be able to resolve exactly one valid module root from the archive.

## Integrity

Core calculates SHA-256 over the downloaded ZIP before installation.

The calculated value must exactly match the platform manifest's `SHA256`.

A mismatch aborts installation.

The same exact ZIP hash should be recorded in the per-module manifest.

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
build source/development package
→ calculate development-package SHA-256
→ place ZIP below backend/EmuKit/EmulatorModules/<OS>/<Module>/
→ update `<Module>_Manifest.json`
→ update `EmuKit_<OS>_Manifest.json`
→ remove local development copy from EmuKitModules
→ install through EmuKit development channel
→ test source-package acquisition and emulator lifecycle
→ build the release package for the target OS/architecture
→ calculate release-package SHA-256
→ update `<Module>_Release_Manifest.json`
→ update `EmuKit_<OS>_Release_Manifest.json`
→ test module acquisition and lifecycle through the release channel
```

Development and release packages may have different bytes when the release package compiles the manager into an executable. They must retain the same stable `Id`, intended `ModuleVersion`, emulator-management behavior, and system metadata for that version. Each channel manifest must contain the SHA-256 of the package distributed by that channel.

## Publishing a New Module Version

When publishing a new module version:

1. create a new `<Module>_<Version>.zip`
2. do not overwrite retained packages still referenced by the module catalogue
3. calculate SHA-256
4. add the new version to backend `<Module>_Manifest.json`
5. update backend `Latest` when appropriate
6. update the backend platform manifest `Version`, `Package`, and `SHA256`
7. test through the development feed
8. build the release package for each supported target
9. add/update the version in `<Module>_Release_Manifest.json`
10. update the release platform manifest `Version`, `Package`, and `SHA256`
11. test through the release channel

## Validation Checklist

Before committing module distribution metadata:

- JSON parses
- platform manifest `SchemaVersion` is supported
- platform manifest `Platform` matches its directory
- every module ID is machine-safe
- every platform entry has `Name`, `Version`, `Package`, and lowercase SHA-256
- every package path is safe and platform-feed-relative
- every package exists
- every SHA-256 matches its exact ZIP
- ZIP contains exactly one valid module root
- extracted module `Id` matches platform manifest key
- extracted module `ModuleVersion` matches platform manifest `Version`
- package is located directly under its module directory
- per-module manifest identifies the same module and platform
- current advertised version exists in the per-module `Versions` map
- platform and per-module manifests agree on package filename and SHA-256
