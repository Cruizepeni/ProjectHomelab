# Example EmuKit Module Package Layout

The current ProjectHomelab module convention uses a multi-file source module and a compact compiled release module.

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
"Manager": "ExampleEmuManager.py"
```

Development-feed layout:

```text
backend/
└── EmuKit/
    └── EmulatorModules/
        └── Windows/
            ├── EmuKit_Windows_Manifest.json
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

Release-feed layout:

```text
Releases/
└── EmuKit/
    └── EmulatorModules/
        └── Windows/
            ├── EmuKit_Windows_Release_Manifest.json
            └── ExampleEmu/
                ├── ExampleEmu_Release_Manifest.json
                └── ExampleEmu_1.0.0_Windows_x86_64.zip
```

Backend/source manifests use `Name_Manifest.json`.

Release-side mirrors use `Name_Release_Manifest.json`.

There is no extra version directory around either ZIP.

After Core downloads and validates a package, the versioned top-level directory is installed under:

```text
<EmuKit runtime>/EmuKitModules/ExampleEmu_1.0.0/
```

The development and release ZIPs are independent exact byte artifacts.

The backend platform and per-module manifests contain the development ZIP SHA-256.

The release platform and per-module manifests contain the release ZIP SHA-256.

The compiled manager must implement:

```text
ExampleEmuManager.exe <check|install|uninstall|repair|update> --json
```

and emit only strict JSONL progress/result records on stdout.
