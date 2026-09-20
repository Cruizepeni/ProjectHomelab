# EmuKit Updater

## Purpose

`EmuKitUpdater` is EmuKit's disposable internal Core-update module.

It exists because a running Core cannot safely replace its own executable/version directory in place.

Updater is infrastructure, not an emulator.

It must not appear in:

- the emulator catalogue
- `Install All`
- `Get Emulator Catalogue`
- normal emulator lifecycle commands

## Source Location

```text
SourceCode/EmuKit/EmuKitModules/Updater/
├── EmuKitUpdater_Manifest.json
└── EmuKitUpdater_1.0.0.zip
```

Source package:

```text
EmuKitUpdater_1.0.0.zip
└── EmuKitUpdater_1.0.0/
    └── EmuKitUpdater.py
```

## Release Location

Windows example:

```text
Resources/EmuKit/EmuKitModules/Windows/Updater/
├── EmuKitUpdater_Release_Manifest.json
└── EmuKitUpdater_1.0.0_Windows_x86_64.zip
```

Release package:

```text
EmuKitUpdater_1.0.0_Windows_x86_64.zip
└── EmuKitUpdater_1.0.0/
    └── EmuKitUpdater.exe
```

## Update Flow

1. Core checks the Core release manifest.
2. Core downloads and validates the target Core release package.
3. Core acquires and validates the platform Updater package.
4. Core stages the next Core release.
5. Core launches Updater with explicit source, target, process, and relaunch parameters.
6. Core exits.
7. Updater waits for the old Core process to terminate.
8. Updater replaces the old Core runtime with the staged release.
9. Updater relaunches the new Core with fresh-update handoff data.
10. The new Core completes migration/cleanup.

## Safety Rules

Updater must:

- validate paths before destructive work
- operate only on explicitly supplied Core targets
- avoid using the emulator catalogue as authority
- preserve only state defined by the Core update contract
- surface failures clearly
- remain disposable after a successful update

## Packaging Cleanliness

Updater source and release packages must not contain:

- `__pycache__`
- `.pyc`
- `.pyo`
- build/temp output outside the declared package root
