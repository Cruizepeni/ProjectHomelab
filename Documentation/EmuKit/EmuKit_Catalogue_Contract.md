# EmuKit Catalogue Contract

## Purpose

The platform catalogue is EmuKit's public discovery and relationship database.

It answers:

- what emulator projects are supported
- what brands are represented
- what systems are represented
- which emulator supports which system
- which systems an emulator supports
- meaningful aliases
- the recommended primary emulator for each system

The catalogue does not describe local installation state.

## Format

The catalogue remains JSON.

JSON is the canonical machine-readable source because identities, aliases, relationships, arrays, validation, and schema evolution are core runtime concerns. Human-readable Markdown documentation may be generated from the JSON, but Markdown is not the runtime catalogue database.

## Schema 1

```json
{
  "SchemaVersion": 1,
  "Version": 1,
  "Platform": "Windows",
  "Emulators": {
    "exampleemu": {
      "Name": "ExampleEmu",
      "Aliases": [],
      "Systems": [
        "example.exampleconsole"
      ]
    }
  },
  "Brands": {
    "example": {
      "Name": "Example",
      "Aliases": [],
      "Systems": {
        "example.exampleconsole": {
          "Name": "Example Console",
          "Aliases": [
            "EC"
          ],
          "Emulators": [
            "exampleemu"
          ],
          "RecommendedPrimary": "exampleemu"
        }
      }
    }
  }
}
```

## Entity IDs

IDs are stable machine identities.

Examples:

```text
mgba
nintendo.gameboyadvance
microsoft.xbox360
sony.playstation2
```

Display names and aliases may change without changing a stable ID.

## Reciprocal Relationships

Relationships must be reciprocal.

If:

```json
"exampleemu": {
  "Systems": ["example.exampleconsole"]
}
```

then the system must also contain:

```json
"Emulators": ["exampleemu"]
```

Core validates reciprocal relationships.

## Recommended Primary

Every system declares exactly one `RecommendedPrimary`, and that emulator ID must exist in the system's `Emulators` list.

User overrides do not modify the catalogue. They live in settings.

## Alias Policy

Aliases represent real alternate names, regional names, and common abbreviations.

Do not add aliases solely for capitalization, whitespace, underscore, or hyphen variations that Core normalization already resolves.

Do not use a hardware model code as a system alias unless users genuinely use that code as a name for the whole system.

## Catalogue Commands

### Complete Catalogue

```text
Get Catalogue
```

### Section Catalogues

```text
Get Brand Catalogue
Get System Catalogue
Get Emulator Catalogue
```

The System Catalogue is flattened for presentation and brand-qualifies each system name.

### Entity Catalogues

```text
Get <Brand> Catalogue
```

returns systems for that brand.

```text
Get <System> Catalogue
```

returns emulators supporting that system.

```text
Get <Emulator> Catalogue
```

returns systems supported by that emulator.

## Catalogue vs Info

Catalogue commands answer relationships.

Info commands answer detailed metadata.

For example:

```text
Get MesenCE Catalogue
```

answers which systems MesenCE supports.

```text
Get MesenCE Info
```

answers what EmuKit knows about MesenCE, including module/emulator versions, description, links, license, host support, source metadata, and supported systems when that metadata is available.

## Future Enrichment

Schema 1 may be enriched with optional descriptive metadata as long as existing identity and relationship semantics remain stable.

Possible future system or brand metadata includes:

- description
- official website
- documentation
- release year
- manufacturer
- platform family
- media type

Any catalogue byte change requires recalculating the catalogue SHA-256 in every platform manifest distributing that exact catalogue copy.
