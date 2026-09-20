# Example Module Info

A public module Info JSON combines technical implementation metadata with useful emulator identity/help metadata.

```json
{
  "Version": 1,
  "Id": "exampleemu",
  "Name": "ExampleEmu",
  "Aliases": [],
  "ModuleVersion": "1.0.0",
  "EmulatorVersion": "4.2.0",
  "Description": "A concise description of the emulator project.",
  "Links": {
    "Website": "https://example.invalid/",
    "Repository": "https://github.com/example/example",
    "Wiki": null,
    "Documentation": "https://example.invalid/docs",
    "EmuKitModuleDocumentation": "https://github.com/Cruizepeni/ProjectHomelab/blob/main/Documentation/EmuKit/Modules/ExampleEmu_Module.md"
  },
  "Manager": "ExampleEmuManager.py",
  "DependencyPath": "Emulators/ExampleEmu",
  "LaunchPath": "Emulators/ExampleEmu/example.exe",
  "WorkingDirectory": "Emulators/ExampleEmu",
  "Lifecycle": {
    "ProcessName": "example.exe"
  },
  "Channel": "Stable",
  "Systems": {
    "example.exampleconsole": {
      "Name": "Example Console",
      "Aliases": ["EC"],
      "Brand": {
        "Id": "example",
        "Name": "Example",
        "Aliases": []
      },
      "Platform": {
        "Id": "console",
        "Name": "Console",
        "Aliases": []
      },
      "LaunchArguments": ["{fullscreen}", "{game}"],
      "FullscreenArgument": "--fullscreen"
    }
  }
}
```

`Links.Documentation` is upstream emulator documentation.

`Links.EmuKitModuleDocumentation` is ProjectHomelab's documentation for the EmuKit module.
