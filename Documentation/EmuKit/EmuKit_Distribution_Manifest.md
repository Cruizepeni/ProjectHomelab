# EmuKit Distribution Manifests

## Purpose

EmuKit uses separate manifests for:

- Core source/release metadata
- platform module acquisition
- platform catalogue distribution
- per-module version/package history
- internal infrastructure modules such as Updater

Distribution metadata describes what can be acquired. It does not describe local installed state.

## Repository Layout

Development emulator feed:

```text
SourceCode/EmuKit/EmuKitModules/<OS>/
├── EmuKit_<OS>_Manifest.json
├── EmuKit_<OS>_Catalogue.json
└── <Module>/
    ├── <Module>_Manifest.json
    └── <Module>_<ModuleVersion>.zip
```

Updater source:

```text
SourceCode/EmuKit/EmuKitModules/Updater/
├── EmuKitUpdater_Manifest.json
└── EmuKitUpdater_<Version>.zip
```

Release emulator feed:

```text
Resources/EmuKit/EmuKitModules/<OS>/
├── EmuKit_<OS>_Release_Manifest.json
├── EmuKit_<OS>_Catalogue.json
├── <Module>/
│   ├── <Module>_Release_Manifest.json
│   └── <Module>_<ModuleVersion>_<OS>_<Architecture>.zip
└── Updater/
    ├── EmuKitUpdater_Release_Manifest.json
    └── EmuKitUpdater_<Version>_<OS>_<Architecture>.zip
```

Core source:

```text
SourceCode/EmuKit/EmuKitCore/
├── EmuKit_Core_Manifest.json
└── EmuKit_1.0.0/
```

Core release:

```text
Releases/EmuKit/
├── EmuKit_Core_Release_Manifest.json
└── EmuKit_<Version>_<OS>_<Architecture>.zip
```

## Platform Manifest

Development:

```text
EmuKit_<OS>_Manifest.json
```

Release:

```text
EmuKit_<OS>_Release_Manifest.json
```

Schema 1 development shape:

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
  "Modules": {
    "exampleemu": {
      "Name": "ExampleEmu",
      "Aliases": [],
      "Version": "1.0.0",
      "Package": "ExampleEmu/ExampleEmu_1.0.0.zip",
      "SHA256": "replace-with-package-sha256"
    }
  }
}
```

## Catalogue Hash

The catalogue descriptor SHA-256 is the SHA-256 of the exact catalogue bytes.

Any catalogue byte change requires recalculating every platform manifest distributing that copy.

## Module Package Hash

A platform module entry SHA-256 is the SHA-256 of the exact module ZIP bytes.

If any file inside the module ZIP changes:

1. rebuild the module ZIP
2. recalculate the module ZIP SHA-256
3. update the per-module manifest
4. update the platform manifest

If the module change also changes catalogue metadata, recalculate the catalogue SHA-256 as well.

## Per-Module Manifest

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
      "SHA256": "replace-with-package-sha256"
    }
  }
}
```

`ModuleVersion` and `EmulatorVersion` are separate.

## Package Naming

Development:

```text
<Module>_<ModuleVersion>.zip
```

Windows x86_64 release:

```text
<Module>_<ModuleVersion>_Windows_x86_64.zip
```

Each ZIP contains one versioned root:

```text
<Module>_<ModuleVersion>/
```

## Core Source Manifest

```json
{
  "SchemaVersion": 1,
  "Id": "emukit-core",
  "Name": "EmuKit Core",
  "Channel": "development",
  "Latest": "1.0.0",
  "Versions": {
    "1.0.0": {
      "Status": "supported",
      "Source": "EmuKit_1.0.0",
      "EntryPoint": "EmuKit.py"
    }
  }
}
```

## Internal Modules

Infrastructure modules are separate from emulator modules and are not included in the emulator catalogue.

The Updater is the current internal module.

## Windows Core Build

The canonical Windows Core release is one console-subsystem executable.

The package ZIP contains:

```text
EmuKit_<Version>/
└── EmuKit.exe
```

The release manifest SHA-256 is calculated from the exact release ZIP, not the executable alone.

## Clean Packaging

Source and release ZIPs must not contain:

- `__pycache__`
- `.pyc`
- `.pyo`
- temporary extraction directories
- build directories not part of the declared package
