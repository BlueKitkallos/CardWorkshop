# Guide

## Packs

- You can edit the 81 base game packs and add up to 20 new boosters. A new booster needs at least one Ultra, one Super, one Rare and four Commons.
- Each rarity shows its cards as pictures. Click **Text** to edit them as a list, one card per line. The buttons above the rarities scroll to each one.
- Drag a card to another rarity to move it, or drop it on another card to change the order. You can search cards by name, ID or passcode.
- Alternate artworks are separate cards with their own IDs. The card panel also lists the packs that hold the other artworks.
- A card can be in several packs, with a different rarity in each. The game still treats one of them as its main pack: the card detail screen and the password shop use that one, and the Workshop keeps it when it can.
- To change a pack image, click **Replace pack image** or drag a picture onto the pack header. It is cropped to 64 × 128 and saved in the project, and the game's three pack sizes are made from it. A new pack without an image uses the image of the first base game pack.

## Decks and CPUs

- You can edit the base game CPU and rental decks, or copy a deck to make a new one. Each card shows as one line like `3 × Card name`, with + and − buttons. Going down to zero removes the card.
- Main holds 40 to 60 cards, Extra and Side up to 15 each. Fusion and Synchro monsters go in Extra, other cards in Main, and any card can go in Side. You can have at most three copies of a card across all three.
- **Project label** is the deck's name in the Workshop only. **Deck name in game** is the name players see.
- **Free Duel CPUs** has a section for each list: CPU Duel, CPU Turbo Duel, CPU Tag Duel and CPU Tag Turbo Duel. Each one shows the base game CPUs first, then the ones you added.
- You can change a base game CPU's name, portrait, deck, key card, rating and dialogue. Anything you leave alone stays as it is in the game. The dialogue starts from the CPU's own lines, so you only rewrite the ones you want. **Reset to base game** undoes all your changes to that CPU.
- You can add up to 196 Free Duel CPUs. **+ New CPU** asks which list it goes in. Each one gets its own deck, a base game portrait, a key card, and a base game CPU whose dialogue and rating it starts with. They are unlocked from the start.
- In CPU Tag Duel and CPU Tag Turbo Duel you pick a team, so an added tag CPU needs a **Partner** and a **Team name**. The partner can be any base game CPU or another CPU you added. Your own partner still comes from story mode.
- **Copy base game CPU** copies a CPU from the game, with its own copy of the deck. The CPU uses the base game dialogue until you edit a line. Dialogue and rating are under **Dialogue & rating**. Up to 78 CPUs can have their own dialogue, and that counts base game CPUs whose lines you changed.

## Banlists

- You can make one classic list and one points list. In a classic list each card is Forbidden, Limited, Semi-limited or Unlimited. In a points list each card costs 0 to 99 points, and a deck must stay within the budget you set. Main, Extra and Side all count.
- **New list** asks which kind to make. **Copy Retro-Genesys** fills the points list with the Retro-Genesys values and skips cards that aren't in the base game. **Copy base game list** copies one of the game's own lists into the classic list.
- A classic list can limit up to 248 cards. Each artwork of a card counts separately.
- Your lists appear in the game's list menu. **Default for a new game** picks the list a new save starts with. Alternate artworks share a card's limit and points.

## Optional patches

- **CPU speed**: makes the CPU think about three times faster. It still plays the same moves.
- **QoL**: adds View Mode to Free Duel and Duelist Info to User Settings, makes menus open faster and fixes a few small duel bugs.
- **UI fixes**: menus fade through black instead of white, and the green band around attack cut-ins and the magenta flash at boot are gone. Sound effects no longer drop out with the larger duel themes.
- **Fix card effects**: 23 cards that don't work as written, such as Reeze, Chain Whirlwind and Pot of Duality, now follow their text.
- **Fix text errors**: fixes typos in Speed Spells, the Starter Deck description and the story, which now says "she" for a female player.
- **Better pack opening**: packs open with a 3D reveal, using graphics and sounds from your own WC2010 ROM (USA or Europe). Click **Import WC2010 ROM** and it turns on. The Workshop only keeps that ROM until you close it, so import it again next time (`--rom10 donor.zip` also works).
- **Shop instead of WFC**: the main menu's Wireless button becomes a Shop holding Card Shop and Password, which move out of the Duelist Menu. Local wireless play moves to User Settings > Legacy Wi-Fi, and Nintendo Wi-Fi Connection is removed.

Turning on CPU speed, QoL, UI fixes, Fix card effects and Fix text errors together gives you the QoL patch 1.1a.

## Working

- **Undo** and **Redo** go back and forward through up to 40 edits, including deletions and copied lists. Ctrl+Z and Ctrl+Shift+Z work when you aren't typing in a field. Ctrl+S saves the project, including the field you are editing.
- A card the game doesn't have stays in the project as a draft. You can keep editing and saving, but you need to replace it before you can export.
- **Check project** lists everything that would stop an export, and export runs the same check first. Each problem has an **Open** button that takes you to the pack, deck, CPU or list.
- The browser also keeps a recovery copy of your work when it has room.
