# Example EmuKit Module Package Layout

A recommended module package contains one versioned top-level module directory.

```text
ExampleEmu_1.0.0.zip
└── ExampleEmu_1.0.0/
    ├── EmuKitExampleEmuInfo.json
    ├── ExampleEmuManager.py
    └── module-owned supporting files
```

The corresponding development-feed layout is:

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

The release feed mirrors the same layout:

```text
Releases/
└── EmuKit/
    └── EmulatorModules/
        └── Windows/
            ├── EmuKit_Windows_Manifest.json
            └── ExampleEmu/
                ├── ExampleEmu_Manifest.json
                └── ExampleEmu_1.0.0.zip
```

There is no extra version directory around the ZIP.

After Core downloads and validates the package, the top-level module directory is installed under:

```text
<EmuKit runtime>/EmuKitModules/ExampleEmu_1.0.0/
```

The package SHA-256 recorded by the platform manifest and per-module manifest must match the exact ZIP bytes.
