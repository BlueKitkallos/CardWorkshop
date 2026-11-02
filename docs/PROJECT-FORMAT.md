# Project file

A project is a UTF-8 JSON file with the `.wcmod.json` extension. It holds the edits only, never game data: pack lists, decks, CPUs, banlists, enabled patches and imported pack images. Other tools (a story editor, a music tool) read and write the same file and add their own sections.

This page describes format version 2. The reference code is in `model.py` (`working`, `to_file`, `read_project`).

## Header

```json
{
  "format": "wc-mod-project",
  "format_version": 2,
  "game": "wc2011-eu",
  "base_sha1": "7617788d197ffd45d2ab2bb6deadbf0f9874e2fa",
  "name": "My mod",
  "sections": { }
}
```

| Field | Meaning |
|---|---|
| `format` | always `wc-mod-project` |
| `format_version` | layout of the header and of `sections`. A reader refuses a higher value than it knows. |
| `game` | adapter id; `wc2011-eu` is the only one |
| `base_sha1` | SHA-1 of the clean ROM the project applies to |
| `name` | project name, not empty |
| `sections` | one object per tool or domain |

## Sections

Every section is an object with an integer `version` (1 or more). It may carry `"rom": false` when it never changes the exported ROM (notes, editor state). Without it, a section counts as changing the ROM.

Sections of the Workshop:

| Section | Version | Content |
|---|---|---|
| `packs` | 1 | `items`: packs. `id` 1-81 base game, 97-116 added. `name`/`desc`: seven languages (`e f g i s j k`). `cards`: `ultra`, `super`, `rare`, `common` lists of card references. Optional `image` (64 × 128 PNG data URL), `price` (added packs). |
| `decks` | 1 | `items`: decks. `file`, `name`, `main`, `extra`, `side` (card references). |
| `cpus` | 3 | `items`: added Free Duel CPUs. `chara`, `name`, `deck`, `portrait`, `template_deck`, `key_card`, `turbo`; optional `rating`, `deck_name`, `talk` (28 lines), and for CPU Tag Duel `tag: true`, `partner` (a character id, base game or added) and `team_name`. `turbo` with `tag` is CPU Tag Turbo Duel. `base`: changes to base game Free Duel CPUs, keyed by character id as a string (`"301"`); each value holds only the changed fields among `name`, `deck`, `deck_name`, `portrait`, `key_card`, `rating`, `talk`. A base CPU's `talk` holds only the changed lines, keyed by line number 0-27 as a string. |
| `banlists` | 1 | `items`: at most one `classic` (`cards`: reference → 0-3) and one `points` list (`cards`: reference → 0-99, `cap`). `default`: `base`, `classic` or `points`. |
| `patches` | 1 | `enabled`: patch ids (`cpu-speed`, `view-mode`, `pack-opening`, `flash-fixes`, `wfc-shop`). |

`packs` and `decks` are required: the Workshop writes all 81 base game packs and every base game deck. The others may be absent.

Base game CPU changes: a field equal to the base game value is dropped on save, and a CPU with no changes left is removed. A base game CPU's `deck` names the deck it plays; the export writes that deck's cards into the CPU's own base game deck file. The base game Free Duel CPUs are characters 301-360 (CPU Duel), 401-420 (CPU Turbo Duel), 361-400 (CPU Tag Duel, 20 teams) and 421-440 (CPU Tag Turbo Duel, 10 teams).

Card references: `id:<card id>`, a passcode, or an English card name. `id:` is what the Workshop writes.

## Reference ids

Ids never change when other items are added, removed or reordered. Point at items with these strings:

| Reference | Item |
|---|---|
| `pack:<id>` | pack `id`, e.g. `pack:97` |
| `deck:<file>` | deck `file`: a base game file name (`default_jf.ydc`) or a copy, `user_<uuid>.ydc` |
| `cpu:<chara>` | added CPU `chara`, 465 or more, e.g. `cpu:465`, or a base game Free Duel CPU, e.g. `cpu:301`; it is also the game's character number |
| `banlist:<id>` | `banlist:classic`, `banlist:points` |

A CPU's `deck` is a deck `file`. Deleting an item does not renumber the others; a reference to a deleted item is reported as missing.

## Versioning rules

- A section's owner raises its `version` for any change an older reader would misread (renamed or retyped field, new meaning). A reader refuses a project with a known section newer than it supports, with "made with a newer tool".
- New data from another tool goes in a new section, never as new fields in someone else's section.
- `format_version` changes only when the header or the section envelope changes.
- Readers migrate older versions on load and write the current one. Format 1 (all lists at the top level, `version: 1`) is read and saved as format 2; CPUs without `chara` get `465 + position` once, at migration.
- `cpus` version 1 has no `base`; it is read as no changes to base game CPUs. Version 2 stores a base CPU's `talk` as 28 lines; it is read as numbered lines and the unchanged ones are dropped. Both are saved as version 3.

## Unknown sections

A tool keeps every section it does not know exactly as it read it and writes it back unchanged. It never blocks opening.

Exporting a ROM with an unknown section that changes the ROM (no `"rom": false`) is blocked: "Section “name” was made with a newer tool. Update the Workshop to export." The Workshop never drops such a section silently.

## Encoding

Write UTF-8, 2-space indent, non-ASCII characters unescaped, object keys in their existing order, a final newline (Python: `json.dumps(p, ensure_ascii=False, indent=2) + "\n"`). Files written this way round-trip through the Workshop byte for byte. The Workshop writes its own sections first, then unknown ones in the order read.
