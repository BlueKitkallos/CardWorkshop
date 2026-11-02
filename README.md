# Card Workshop

Edit packs, decks, CPU opponents and banlists of Yu-Gi-Oh! 5D's World Championship 2011: Over the Nexus (Europe), and share the result as a BPS patch.

## Download

Get the latest version from [Releases](https://github.com/BlueKitkallos/CardWorkshop/releases). It opens in your browser at `http://127.0.0.1:8792`.

- Windows: extract `CardWorkshop-windows.zip` and double-click `CardWorkshop.exe` in the `CardWorkshop` folder. If Windows warns about an unknown publisher, click "More info", then "Run anyway".
- Linux: open a terminal in the folder you downloaded to and run `tar xzf CardWorkshop-linux.tar.gz`, then `./CardWorkshop/CardWorkshop`.
- macOS is untested: right-click `CardWorkshop` and choose Open the first time.

## From source

Needs Python 3.10+.

```
python3 -m pip install -r requirements.txt
python3 tools/pack_editor.py
```

Options: `--rom clean.nds`, `--port 8792`, `--no-browser`.

From source, added packs, shared cards, added CPUs, banlists and the optional patches also need the ARM GNU toolchain and armips: see `docs/DEVELOPMENT.md`. Edits to base game packs, decks and text need only Python.

## Use

1. Choose your clean `.nds`. Only the European dump with SHA-1 `7617788d197ffd45d2ab2bb6deadbf0f9874e2fa` is accepted.
2. Edit packs, decks, CPUs and banlists. **Save project** downloads a `.wcmod.json`.
3. **Export patch + project** downloads `mod-export.zip`: `mod.bps`, the project and a build report.
4. Apply `mod.bps` to a clean dump with any BPS patcher.

Builds with added packs use a larger save type: start a new save with them. The Better pack opening patch needs your own WC2010 ROM, from the USA or Europe.

## More

- `docs/GUIDE.md`: editing packs, decks, CPUs and banlists; optional patches
- `docs/DEVELOPMENT.md`: running from source, toolchain, tests
- `docs/PROJECT-FORMAT.md`: the `.wcmod.json` project file

## Credits

The release packages include:

- Python (PSF License)
- ndspy (GPL-3.0-or-later)
- NumPy (BSD-3-Clause and others) and Pillow (MIT-CMU), with the libraries they bundle
- PyInstaller bootloader (GPL-2.0-or-later with the bootloader exception)
- Arm GNU Toolchain: GCC, Binutils, libgcc (GPL-3.0-or-later; libgcc with the GCC Runtime Library Exception)
- armips (MIT)
- Cinzel font (SIL Open Font License 1.1). It is also in this repository, with its licence in `mod/art/fonts/cinzel/`.

The Workshop's own code is under the MIT license. The release packages also contain GPL parts (ndspy, GCC and Binutils), so they are shared under the GPL's terms. Each package lists every part and its version in `CREDITS.md`. The licence texts are in its `licenses/` folder. The source code of the GPL and LGPL parts is attached to each release.

## Disclosure

Parts of the code were written with the help of AI coding agents.

## Legal

Card Workshop is an unofficial fan project, made for free and not sold. It is not affiliated with, endorsed, sponsored or approved by Konami, Konami Digital Entertainment, Kazuki Takahashi, Studio Dice, Shueisha, Nintendo, or anyone else holding rights to Yu-Gi-Oh! or the Nintendo DS.

Yu-Gi-Oh!, the game titles, card names, card art, characters and logos are trademarks and copyrights of their owners. Nintendo DS is a trademark of Nintendo.

This repository contains no ROMs, game code, art, music or text from any game. Card names and passcodes appear only as identifiers in the included Retro-Genesys points list. You supply your own clean ROM.

A patch made with the Workshop holds the differences between a clean ROM and the edited one, made by whoever built the mod. Modders are responsible for making sure their patches contain only work they have the right to share. Players are responsible for what they apply.

The software is provided as is, without warranty of any kind, under the MIT license (see `LICENSE`). The authors are not liable for any damage to files, saves or hardware, or for how anyone uses the tool or the patches made with it.
