# Development

## Layout

- `tools/pack_editor.py`: the local server and entry point
- `tools/community_editor/`: page (`index.html`, `app.js`, `style.css`), project model, ROM adapter, export
- `tools/community_editor/runtime/`: C and armips sources of the in-game hooks, built per export from the project's content
- `mod/w11fast/`, `mod/w11view/`: CPU speed, QoL and UI fix sources
- `variants/dimension-break/src/`: pack opening and Shop menu sources shared with Dimension Break, a WC2011 rom hack built from the same repository
- `mod/art/`: Shop button artwork and heading font (OFL)
- `variants/retro-genesys/`, `mod/test/points/`: the Retro-Genesys points list
- `tools/*.py`, `tools/wc2011/*.py`: ROM, archive, card database, deck, pack and BPS libraries
- `tools/games/*.json`: game profiles (offsets, hashes, injection layout)
- `packaging/`: release launcher and toolchain bundling

## Toolchain

From source, some exports compile native code. Added packs, cards shared between packs, added CPUs, banlists, Better pack opening, the UI fixes and Shop instead of WFC need `arm-none-eabi-gcc` and armips. CPU speed and QoL need only `arm-none-eabi-gcc`. Edits to base game packs, decks and text need neither.

- ARM GNU Toolchain (`arm-none-eabi`): set `ARM_TOOLCHAIN` to its `bin` folder (default `~/tools/arm-gnu-toolchain/bin`).
- [armips](https://github.com/Kingcom/armips): set `ARMIPS` to the binary (default `~/tools/bin/armips`).

Release builds bundle both (see `.github/workflows/build.yml` and `packaging/`). `packaging/build_app.py` also writes `CREDITS.md` and `licenses/` into each package. The workflow downloads the GPL source archives it lists and attaches them to tagged releases.

## Export internals

Each export starts again from the clean ROM. It writes the changed archives and builds the hook code the project needs. Then it applies the BPS back to the clean ROM to check it. Added packs need more save space, so the export switches the save type to FLASH 2 Mbit with the `YG8P` loader identifier. Edits to base game packs alone keep the original save type.

Hook code and its variables sit under the arena top, below the QoL code. With Shop instead of WFC, the Nintendo WFC rows are gone and the variables go into the idle WFC buffers instead.

## Tests

```
python3 -m unittest discover -s tools/community_editor -p 'test_*.py' -v
WC_EDITOR_TEST_ROM=/path/to/clean.nds python3 -m unittest discover -s tools/community_editor -p 'test_*.py' -v
```

With a ROM, the tests also build real exports. They check that an unedited export is byte-identical, that shared cards keep their rarities, and that edited decks, text and art come through. A combined export adds a pack, a CPU, both banlists and every optional patch. It adds Better pack opening when `WC_EDITOR_TEST_ROM10` names a WC2010 ROM (USA or Europe). It writes `build/community-editor-combined/combined.nds`, which the banlist probe reads.

Native checks run the exported ROM in melonDS under Xvfb. `MELON` names the melonDS binary and `GYM_MELON_CFG` its config folder. They start from a boot rig and read RAM. They never walk menus or play a duel.

```
python3 tools/community_editor/smoke/run.py --rom /path/to/clean.nds
python3 tools/community_editor/banlist_smoke/run.py
python3 tools/community_editor/menu_smoke/run.py --rom /path/to/clean.nds
```

`smoke/run.py` opens the shop and checks the card lists and rarity filters. It draws from base game packs and an added pack, and checks the added CPU's deck. It also loads the first CPU Duel and CPU Turbo Duel opponents the way the Free Duel list does, and checks that their changed name, deck, portrait, rating, key card and dialogue come through.

`banlist_smoke/run.py` reads what the game's list loader returns for a Limited card (1) and a 99-point card (icon status 115, `0x10 + 99`). The point-icon threshold is raised to 0x100 so every value from 0 to 99 shows.

`menu_smoke/run.py` exports with Shop instead of WFC and the QoL patches. It loads each main-menu fixture and reads the rows from RAM. It expects Shop, Duelist Menu, User Settings with Duelist Info and Legacy Wi-Fi, and a wireless list with no WFC rows.

Browser checks (Chrome and the Python `websockets` package):

```
python3 tools/community_editor/browser_check.py --rom /path/to/clean.nds
```

Output goes under `build/`.
