# Example EmuKit Module Package Layout

A recommended module package contains one top-level module directory.

```text
ExampleEmu_1.0.0.zip
└── ExampleEmu/
    ├── EmuKitExampleEmuInfo.json
    └── ExampleEmuManager.py
```

The corresponding development-feed layout may be:

```text
backend/
└── EmuKit/
    └── EmulatorModules/
        └── Windows/
            ├── EmuKit_Windows_Manifest.json
            └── ExampleEmu/
                └── 1.0.0/
                    └── ExampleEmu_1.0.0.zip
```

After promotion, the exact package may be mirrored to:

```text
Releases/
└── EmuKit/
    └── EmulatorModules/
        └── Windows/
            ├── EmuKit_Windows_Manifest.json
            └── ExampleEmu/
                └── 1.0.0/
                    └── ExampleEmu_1.0.0.zip
```

The package SHA-256 in each manifest must match the exact ZIP bytes.
