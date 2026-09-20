# EmuKit Distribution Manifests

## Purpose

EmuKit uses separate manifests for Core releases, emulator module packages, the platform catalogue, and internal infrastructure modules such as the disposable Core Updater.

Distribution metadata describes what can be acquired. It does not describe local installed state.

## Canonical Repository Layout

Development emulator feed:

```text
SourceCode/EmuKit/EmuKitModules/<OS>/
├── EmuKit_<OS>_Manifest.json
├── EmuKit_<OS>_Catalogue.json
└── <Module>/
    ├── <Module>_Manifest.json
    └── <Module>_<Version>.zip
```

Generic Updater source:

```text
SourceCode/EmuKit/EmuKitModules/Updater/
├── EmuKitUpdater_Manifest.json
└── EmuKitUpdater_<Version>.zip
```

Release emulator/internal-module feed:

```text
Resources/EmuKit/EmuKitModules/<OS>/
├── EmuKit_<OS>_Release_Manifest.json
├── EmuKit_<OS>_Catalogue.json
├── <Module>/
│   ├── <Module>_Release_Manifest.json
│   └── <Module>_<Version>_<OS>_<Architecture>.zip
└── Updater/
    ├── EmuKitUpdater_Release_Manifest.json
    └── EmuKitUpdater_<Version>_<OS>_<Architecture>.zip
```

Core source manifest:

```text
SourceCode/EmuKit/EmuKitCore/EmuKit_Core_Manifest.json
```

Core release manifest and packages:

```text
Releases/EmuKit/
├── EmuKit_Core_Release_Manifest.json
└── EmuKit_<Version>_<OS>_<Architecture>.zip
```

Canonical OS values:

```text
Windows
Linux
Mac
```

## Windows Core Build Contract

The canonical Windows Core release is built from `EmuKit.py` as one console-subsystem executable. `--console` is intentional: it preserves the interactive terminal UI and also allows another process to launch the same executable without a visible window while redirecting its standard streams. Do not publish a second `--noconsole` Core build for the same target.

The canonical EmuKit icon is a shared resource, not a loose Core source file:

```text
Resources/Icons/Features/EmuKit/EmuKit/Icon_EmuKit.ico
```

A Windows build therefore uses the equivalent of:

```powershell
py -m PyInstaller --clean --noconfirm --onefile --console --icon "<repo>/Resources/Icons/Features/EmuKit/EmuKit/Icon_EmuKit.ico" --paths "." --name "EmuKit" EmuKit.py
```

The release ZIP contains the compiled executable under the declared versioned root:

```text
EmuKit_<Version>_Windows_x86_64.zip
└── EmuKit_<Version>/
    └── EmuKit.exe
```

The SHA-256 advertised by `EmuKit_Core_Release_Manifest.json` is the SHA-256 of the exact release ZIP bytes, not the executable inside it.

## Platform Manifest

The platform manifest is Core's runtime distribution index.

Development:

```text
SourceCode/EmuKit/EmuKitModules/<OS>/EmuKit_<OS>_Manifest.json
```

Release:

```text
Resources/EmuKit/EmuKitModules/<OS>/EmuKit_<OS>_Release_Manifest.json
```

Schema 1 shape:

```json
{
  "SchemaVersion": 1,
  "Platform": "Windows",
  "Catalogue": {
    "SchemaVersion": 1,
    "Version": 1,
    "File": "EmuKit_Windows_Catalogue.json",
    "SHA256": "replace-with-catalogue-sha256"
  },
  "Modules": {},
  "InternalModules": {}
}
```

`InternalModules` is optional when empty. It is used for infrastructure packages that Core needs but which are not emulators.

## Catalogue Descriptor

The `Catalogue` descriptor provides:

- catalogue schema
- catalogue version
- filename relative to the platform feed directory
- SHA-256 of the exact catalogue bytes

Example:

```json
"Catalogue": {
  "SchemaVersion": 1,
  "Version": 1,
  "File": "EmuKit_Windows_Catalogue.json",
  "SHA256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
}
```

Any change to the catalogue bytes requires recalculating and replacing this SHA-256 in every platform manifest that distributes that catalogue copy.

## Public Emulator Modules

Example development entry:

```json
"exampleemu": {
  "Name": "ExampleEmu",
  "Aliases": [],
  "Version": "1.0.0",
  "Package": "ExampleEmu/ExampleEmu_1.0.0.zip",
  "SHA256": "replace-with-development-package-sha256"
}
```

Windows release entry:

```json
"exampleemu": {
  "Name": "ExampleEmu",
  "Aliases": [],
  "Version": "1.0.0",
  "Package": "ExampleEmu/ExampleEmu_1.0.0_Windows_x86_64.zip",
  "SHA256": "replace-with-release-package-sha256"
}
```

Package paths must be safe, relative to the platform feed directory, and must not contain `..`.

## Internal Modules

Infrastructure modules are listed separately:

```json
"InternalModules": {
  "updater": {
    "Name": "EmuKit Updater",
    "Kind": "core-updater",
    "Version": "1.0.0",
    "Package": "Updater/EmuKitUpdater_1.0.0_Windows_x86_64.zip",
    "SHA256": "replace-with-updater-package-sha256",
    "RootDirectory": "EmuKitUpdater_1.0.0",
    "Executable": "EmuKitUpdater.exe"
  }
}
```

Core validates internal module IDs, safe paths, package hashes, `RootDirectory`, and `Executable`.

Internal modules are not required to appear in the emulator catalogue.

## Platform Catalogue

The platform catalogue is authoritative public support metadata.

Schema 1:

```json
{
  "SchemaVersion": 1,
  "Version": 1,
  "Platform": "Windows",
  "Emulators": {
    "exampleemu": {
      "Name": "ExampleEmu",
      "Aliases": [],
      "Systems": [
        "example.exampleconsole"
      ]
    }
  },
  "Brands": {
    "example": {
      "Name": "Example",
      "Aliases": [],
      "Systems": {
        "example.exampleconsole": {
          "Name": "Example Console",
          "Aliases": [
            "EC"
          ],
          "Emulators": [
            "exampleemu"
          ],
          "RecommendedPrimary": "exampleemu"
        }
      }
    }
  }
}
```

Core validates reciprocal relationships: if an emulator says it supports a system, that system must list the emulator, and vice versa.

Each system must name a valid `RecommendedPrimary` from its `Emulators` list.

## Per-Module Manifest

Development:

```text
<Module>_Manifest.json
```

Release:

```text
<Module>_Release_Manifest.json
```

Example development manifest:

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
      "SHA256": "replace-with-development-package-sha256"
    }
  }
}
```

The release equivalent uses the target-qualified ZIP name and release ZIP SHA.

The platform manifest is the active acquisition index. The per-module manifest is the retained version catalogue for that module. For the advertised version they must agree.

## Module Package Naming

Development:

```text
<Module>_<ModuleVersion>.zip
```

Windows x86_64 release:

```text
<Module>_<ModuleVersion>_Windows_x86_64.zip
```

There is no extra version directory around the ZIP in the repository.

The ZIP itself contains one versioned module root:

```text
<Module>_<ModuleVersion>/
```

## Core Release Manifest

Core release metadata is separate from module distribution.

```json
{
  "SchemaVersion": 1,
  "Id": "emukit-core",
  "Name": "EmuKit Core",
  "Channel": "release",
  "Latest": "1.0.0",
  "Versions": {
    "1.0.0": {
      "Status": "supported",
      "Targets": {
        "windows-x86_64": {
          "OS": "Windows",
          "Architecture": "x86_64",
          "Package": "EmuKit_1.0.0_Windows_x86_64.zip",
          "SHA256": "replace-with-core-package-sha256",
          "RootDirectory": "EmuKit_1.0.0",
          "Executable": "EmuKit.exe"
        }
      }
    }
  }
}
```

The release ZIP and `EmuKit_Core_Release_Manifest.json` are siblings below `Releases/EmuKit/`.

## Integrity Rules

SHA-256 always describes exact file bytes.

Recalculate the hash when:

- any file inside a ZIP changes
- a compiled executable changes
- a ZIP is recreated with different bytes
- the catalogue changes

Then replace every manifest field that references that exact artifact.

Development and release packages are independent artifacts and normally have different hashes.

## Emulator Module Promotion

```text
finish source module
→ create development ZIP
→ calculate development ZIP SHA
→ update per-module development manifest
→ update development platform manifest
→ update catalogue when support/aliases/relationships changed
→ recalculate catalogue SHA when changed
→ test development acquisition/lifecycle/launch
→ compile target manager
→ create target release ZIP
→ calculate release ZIP SHA
→ update per-module release manifest
→ update release platform manifest
→ publish catalogue copy and matching catalogue SHA
→ test through compiled Core
```

## Updater Promotion

```text
finish generic EmuKitUpdater.py
→ create source EmuKitUpdater_<Version>.zip
→ calculate source ZIP SHA
→ update EmuKitUpdater_Manifest.json
→ compile updater for target OS/architecture
→ create target release ZIP
→ calculate target release ZIP SHA
→ update EmuKitUpdater_Release_Manifest.json
→ add/update InternalModules.updater in platform release manifest
→ verify both release manifests use the same target ZIP SHA
→ test full Core update handoff and rollback
```

## Validation Checklist

Before pushing distribution metadata verify:

- all JSON parses
- all schema/version values are intentional
- platform manifest `Platform` matches its directory
- catalogue descriptor points to the real catalogue filename
- catalogue SHA matches exact catalogue bytes
- catalogue emulator/system relationships are reciprocal
- every `RecommendedPrimary` is valid
- public `Modules` contains emulator modules only
- infrastructure packages use `InternalModules`
- all package paths are safe relative paths
- every advertised package exists
- every advertised SHA matches exact ZIP bytes
- package contains exactly one expected versioned root
- module Info `Id` and `ModuleVersion` match distribution metadata
- system aliases in module Info mirror the catalogue
- source managers and release managers point to the correct entry points
- no `__pycache__`, `.pyc`, `build`, or `dist` artifacts are accidentally packaged
- compiled release behavior is exercised through compiled Core
