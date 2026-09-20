# Example Catalogue Queries

Assume a catalogue contains:

- Nintendo Game Boy Advance
- Ares
- MGBA
- MesenCE

## Whole Catalogue

```text
Get Catalogue
```

Returns the complete brand/system/emulator catalogue.

## System Catalogue

```text
Get System Catalogue
```

Presentation uses brand-qualified names:

```text
Microsoft Xbox
Microsoft Xbox 360
Nintendo Game Boy Advance
Sony PlayStation
Sony PlayStation 2
```

## Brand Entity Catalogue

```text
Get Nintendo Catalogue
```

Lists Nintendo systems.

## System Entity Catalogue

```text
Get Game Boy Advance Catalogue
```

Lists:

```text
Ares
MGBA
MesenCE
```

and identifies the recommended primary.

## Emulator Entity Catalogue

```text
Get MesenCE Catalogue
```

Lists every catalogue system supported by MesenCE.

## Info vs Catalogue

```text
Get MGBA Catalogue
```

answers what systems MGBA supports.

```text
Get MGBA Info
```

answers detailed MGBA metadata such as module/emulator version, description, links, license, host support, source metadata, and supported systems.
