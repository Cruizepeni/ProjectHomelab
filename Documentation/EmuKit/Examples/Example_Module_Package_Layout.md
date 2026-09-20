# Example Module Package Layout

## Repository Development Layout

```text
SourceCode/EmuKit/EmuKitModules/Windows/
├── EmuKit_Windows_Manifest.json
├── EmuKit_Windows_Catalogue.json
└── ExampleEmu/
    ├── ExampleEmu_Manifest.json
    └── ExampleEmu_1.0.0.zip
```

## Development ZIP

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

Do not package:

```text
__pycache__/
*.pyc
*.pyo
build/
dist/
```

## Runtime Module Package

Core extracts the versioned root into its local module area and discovers the single `EmuKit*Info.json` registration.

## Managed Emulator Data

The module installs emulator application data into the path declared by `DependencyPath`, normally:

```text
ROOT/Emulators/ExampleEmu/
```

Module source and emulator application data are separate.
