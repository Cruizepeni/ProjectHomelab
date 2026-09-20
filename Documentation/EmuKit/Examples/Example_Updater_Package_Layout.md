# Example Updater Package Layout

## Source

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

## Windows Release

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

Updater is an internal Core-update module and is not an emulator module.
