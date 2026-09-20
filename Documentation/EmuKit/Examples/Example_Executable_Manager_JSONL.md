# Example Executable Manager JSONL

Core invokes a module manager with one lifecycle operation and `--json`.

```text
ExampleEmuManager.exe install --json
```

or during source development:

```text
python ExampleEmuManager.py install --json
```

The manager writes one JSON object per stdout line.

## Progress

Every progress record includes a meaningful message.

```json
{"type":"progress","percent":5,"stage":"Checking Host","message":"Windows x86_64"}
{"type":"progress","percent":10,"stage":"Preparing Install","message":"Emulators/ExampleEmu"}
{"type":"progress","percent":35,"stage":"Downloading Emulator","message":"exampleemu-4.2.0.zip"}
{"type":"progress","percent":60,"stage":"Validating Emulator","message":"exampleemu-4.2.0.zip"}
{"type":"progress","percent":72,"stage":"Extracting Emulator","message":"exampleemu-4.2.0.zip"}
{"type":"progress","percent":82,"stage":"Installing Emulator","message":"exampleemu.exe"}
{"type":"progress","percent":90,"stage":"Configuring Emulator","message":"portable.ini"}
{"type":"progress","percent":96,"stage":"Verifying Installation","message":"exampleemu.exe"}
{"type":"progress","percent":98,"stage":"Writing Receipt","message":".emukit_install.json"}
{"type":"progress","percent":100,"stage":"Install Complete","message":"Version 4.2.0"}
```

Core may render module `100% Install Complete` provisionally as `99%` and reserve the displayed terminal `100%` for the final lifecycle result.

## Final Result

```json
{"type":"result","result":{"success":true,"module":"exampleemu","operation":"install","state":"installed","message":"ExampleEmu Version 4.2.0 installed successfully.","details":{"version":"4.2.0"}}}
```

The result record, not the preceding completion progress event, determines success.

## Failure Result

```json
{"type":"result","result":{"success":false,"module":"exampleemu","operation":"install","state":"install_failed","message":"ExampleEmu installation failed while validating exampleemu-4.2.0.zip.","error":"checksum_mismatch","details":null}}
```

Core presents the terminal lifecycle state as:

```text
Install Failed
```

Unhandled manager exceptions are also converted into an operation failure result and Core presents the corresponding operation-specific failure stage.

## Check States

Typical `check` result states are:

```text
missing
installed
broken
```

Both single `Install <Emulator>` and `Install All` use Core preflight checks.

Core installs only `missing`, skips `installed`, and reports `broken` for Repair.

## Output Rule

In JSON mode stdout is protocol output. Do not mix regular text, terminal formatting, debug prints, comments, stack traces, or unmanaged child-process output into the stream.
