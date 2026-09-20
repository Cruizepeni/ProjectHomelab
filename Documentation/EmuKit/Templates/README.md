# EmuKit Templates

These templates define the current EmuKit 1.0.0 development contracts.

They are starting points, not emulator implementations.

Before publishing a new module:

1. replace every `ReplaceModule` / placeholder identity
2. implement real emulator-specific lifecycle behavior
3. use the canonical progress vocabulary and include a meaningful message on every progress event
4. identify concrete files, archives, paths, receipts, resources, firmware, and configuration targets in progress messages
5. return authoritative lifecycle result records and allow Core to own final success/failure presentation
6. populate `Description` and `Links`
7. verify system identities against the platform catalogue
8. verify resource metadata against the central EmuKit resource manifest
9. remove all Python comments and docstrings
10. remove `__pycache__`, `.pyc`, and `.pyo`
11. rebuild the module ZIP
12. recalculate per-module and platform-manifest SHA-256 values
13. update the catalogue and catalogue SHA when relationships/aliases change
