# Example Executable Manager JSONL Session

Core invokes a compiled module manager as:

```text
ExampleEmuManager.exe install --json
```

The manager reserves stdout for strict JSONL protocol records.

Example stream:

```json
{"type":"progress","percent":5,"stage":"Checking host","message":null}
{"type":"progress","percent":20,"stage":"Downloading","message":"Downloading ExampleEmu."}
{"type":"progress","percent":55,"stage":"Verifying","message":"Verifying SHA-256."}
{"type":"progress","percent":75,"stage":"Extracting","message":null}
{"type":"progress","percent":95,"stage":"Finalizing","message":null}
{"type":"result","result":{"success":true,"module":"exampleemu","operation":"install","state":"installed","message":"ExampleEmu installed successfully.","details":{"version":"4.2.0"}}}
```

Every record is one complete JSON object followed by a newline.

Progress records are flushed immediately.

Exactly one final result is emitted.

No progress is emitted after the final result.

Plain text, blank stdout lines, malformed JSON, unknown record types, duplicate results, or a missing result are protocol errors.

Diagnostic text that is not part of the machine protocol belongs on stderr.

Successful final results exit `0`.

Unsuccessful final results exit non-zero.
