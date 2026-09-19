# Example EmuKit Updater Package Layout

## Generic Source Package

```text
SourceCode/EmuKit/EmuKitModules/Updater/
├── EmuKitUpdater_Manifest.json
└── EmuKitUpdater_1.0.0.zip
```

```text
EmuKitUpdater_1.0.0.zip
└── EmuKitUpdater_1.0.0/
    └── EmuKitUpdater.py
```

The source ZIP must not contain:

```text
__pycache__/
*.pyc
*.pyo
build/
dist/
```

## Windows x86_64 Release Package

```text
Resources/EmuKit/EmuKitModules/Windows/Updater/
├── EmuKitUpdater_Release_Manifest.json
└── EmuKitUpdater_1.0.0_Windows_x86_64.zip
```

```text
EmuKitUpdater_1.0.0_Windows_x86_64.zip
└── EmuKitUpdater_1.0.0/
    └── EmuKitUpdater.exe
```

The platform release manifest advertises it as:

```json
"InternalModules": {
  "updater": {
    "Name": "EmuKit Updater",
    "Kind": "core-updater",
    "Version": "1.0.0",
    "Package": "Updater/EmuKitUpdater_1.0.0_Windows_x86_64.zip",
    "SHA256": "replace-with-exact-release-zip-sha256",
    "RootDirectory": "EmuKitUpdater_1.0.0",
    "Executable": "EmuKitUpdater.exe"
  }
}
```

The Updater is not included in `Modules` and is not included in `EmuKit_Windows_Catalogue.json`.

## Runtime Staging

Core stages a Core update below its cache, downloads the verified Core package and verified Updater package, extracts the Updater, launches it, and exits.

The Updater is disposable. It does not become a permanently installed emulator module.
