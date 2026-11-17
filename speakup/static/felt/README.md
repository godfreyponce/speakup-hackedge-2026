# Felt look of the child screen

Pre-rendered WebP layers for `/kid`, served at `/felt/<name>`. The page (`kid.js`, `kid.css`) only places them and moves
them with CSS `transform` and `opacity`: no filters, blend modes, blur, canvas or WebGL run on the board.

Buddies: patch, dusty, juniper, toffee (parts from `art/turn/board`). Worlds: meadow, garden, bakery, night. The page loads only the pair
the SLP picked on `/look`; a world's own card, strip and item files are listed with the marks.

| Group | Files | KB |
|---|---|---|
| world: meadow | 10 | 270 |
| world thumbnails | 4 | 37 |
| card, strip, mic, ribbon, marks | 30 | 729 |
| world: garden | 19 | 297 |
| world: bakery | 11 | 190 |
| world: night | 16 | 161 |
| word pictures and words | 20 | 286 |
| speech bubbles | 16 | 194 |
| buddy: patch | 58 | 555 |
| buddy: dusty | 58 | 537 |
| buddy: juniper | 60 | 599 |
| buddy: toffee | 58 | 604 |
| **all images** | **360** | **4460** |

`felt.json` holds every piece's place on the 1280 x 720 stage. Do not edit the images or `felt.json` by hand:
`python scripts/felt/build.py <art folder>` rebuilds them on the laptop from the felt art sources (Pillow, Node,
Playwright and Chrome; nothing here is needed on the board).

Licence: original art made for Speak Up by the team (cut-paper and felt renders from the team's own SVG sources).
No third-party pictures, fonts or code are in this folder.
