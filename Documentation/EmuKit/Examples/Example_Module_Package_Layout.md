# Example EmuKit Emulator Module Package Layout

## Development Package

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

The source Info JSON contains:

```json
"Manager": "ExampleEmuManager.py",
"Lifecycle": {
  "ProcessName": "ExampleEmu.exe"
}
```

Development repository layout:

```text
SourceCode/
└── EmuKit/
    └── EmuKitModules/
        └── Windows/
            ├── EmuKit_Windows_Manifest.json
            ├── EmuKit_Windows_Catalogue.json
            └── ExampleEmu/
                ├── ExampleEmu_Manifest.json
                └── ExampleEmu_1.0.0.zip
```

## Windows x86_64 Release Package

```text
ExampleEmu_1.0.0_Windows_x86_64.zip
└── ExampleEmu_1.0.0/
    ├── EmuKitExampleEmuInfo.json
    └── ExampleEmuManager.exe
```

The release Info JSON contains:

```json
"Manager": "ExampleEmuManager.exe"
```

Release repository layout:

```text
Resources/
└── EmuKit/
    └── EmuKitModules/
        └── Windows/
            ├── EmuKit_Windows_Release_Manifest.json
            ├── EmuKit_Windows_Catalogue.json
            └── ExampleEmu/
                ├── ExampleEmu_Release_Manifest.json
                └── ExampleEmu_1.0.0_Windows_x86_64.zip
```

There is no extra version directory around either repository ZIP.

After acquisition Core installs the ZIP's versioned root below the active Core runtime:

```text
<Core runtime>/EmuKitModules/ExampleEmu_1.0.0/
```

The actual emulator is managed separately below:

```text
ROOT/Emulators/ExampleEmu/
```

## Metadata Synchronization

The module Info system metadata mirrors the platform catalogue.

If a system alias changes:

```text
update platform catalogue
→ update matching module Info JSON(s)
→ rebuild development/release module ZIPs
→ update module package SHA values
→ update platform manifest package SHA values
→ update platform manifest catalogue SHA
```

Do not add per-system `Default`. The catalogue owns `RecommendedPrimary`.

## Manager Protocol

A compiled manager implements:

```text
ExampleEmuManager.exe <check|install|uninstall|repair|update> --json
```

and emits strict JSONL progress/result records on stdout.

Lifecycle child programs must not leak routine output into manager stdout.
