# PERCEPT-R test set

This is the fixed set of PERCEPT-R clips that #2 scores the model against. It is the number
behind "agrees with a trained listener." In the presentation, say: "on clips where listeners
mostly agreed."

## Counts

From the run on Nov 3, 2026, on `PERCEPT-R 2.2.2py`:

| position | correct | wrong | total |
|---|---|---|---|
| start-r | 75 | 75 | 150 |
| end-r | 75 | 75 | 150 |
| total | 150 | 150 | 300 |

- Held-out speakers: 55 of the 173 children in the corpus.
- Ages of the held-out speakers: 72 to 143 months (6 to 11 years).
- Training pool: 105,647 clips. The speaker hold-out removes 21,639 (about 20%) and leaves 84,008.
- Label pickles skipped because they are not one float: 13.
- Speakers skipped because their age is not one integer: 0.

Result, Nov 3, 2026: `arti-v0` agreed with the listeners on 258 of 300 clips. See
`docs/model-timing.md`.

## Rules

- Children only: age 144 months (12 years) or less.
- Clear labels only. A label is the share of listeners who heard the r as correct. 0.25 or less
  counts as wrong, 0.75 or more counts as correct, and anything in between stays out.
- Whole speakers are held out. The script shuffles the children with seed 2026, then takes
  them in that order until every cell can be filled. Each held-out speaker gives at most one
  clip per word, picked at random from that speaker's clear clips of the word.
- 75 clips per cell, picked at random from the held-out speakers' clips.
- Start words: rabbit, rain, ring, rocket, red, rock, run, rug, rose.
- End words: car, door, bear, star, chair, floor, hair, pear, deer.
- Labels and ages are read with `pickletools.genops`, never unpickled. A label that is not
  exactly one float is skipped and counted. An age that is not exactly one integer skips the
  speaker.

Lexi reviews the word lists.

## For #2

Train on no clip from any speaker in `data/percept-r/test-speakers.txt`. Skipping only the 300
clips in the test set is not enough.

## Rebuild

From the main checkout:

```bash
python3 -I scripts/pick_test_set.py data/percept-r/PERCEPT-R.zip
```

The script writes `data/percept-r/test-set.csv` and `data/percept-r/test-speakers.txt`. Both
are gitignored. Nothing from the corpus is committed: TalkBank's media rule covers the clips,
the release we use says CC BY-ND 4.0, and TalkBank's default is CC BY-NC-SA 4.0. See
[License](#license). Raf runs the same command on his copy and must get byte-identical files.

## License

What the sources say, as read on Nov 10, 2026:

- The release we use, `PERCEPT-R 2.2.2py`, has one text file, `PERCEPT-R 2.2.2py/README.txt`
  in `PERCEPT-R.zip`. It says: "PERCEPT-R 2.2.2py is licensed under a Creative Commons
  Attribution-NoDerivatives 4.0 International License (CC BY-ND 4.0)", and links
  https://creativecommons.org/licenses/by-nd/4.0/. No web page found so far says BY-ND.
- [TalkBank Ground Rules](https://talkbank.org/0share/rules.html): "Except where otherwise
  indicated, the use of TalkBank data is governed by the Creative Commons CC BY-NC-SA 4.0
  copyright license." Also: "TalkBank media materials cannot be redistributed on the web
  without case-by-case permission from the corpus contributor", and "Materials can be used
  locally for instructional purposes if access is closely controlled."
- The [PERCEPT-R corpus page](https://talkbank.org/phon/access/Clinical/PERCEPT-R.html) names
  no license. It says "any use of data from this corpus must be accompanied by at least one of
  the above references".
- The [contributor's permission form](https://talkbank.org/phon/permissions/Clinical/PERCEPT-R.pdf)
  lists the restrictions on use as "None."
- Benway et al. (2023): "The PERCEPT project is distributed for noncommercial use through
  PhonBank".

The sources do not say whether the README's BY-ND replaces TalkBank's BY-NC-SA default for this
release. For trained models TalkBank answered directly (Nov 13): do not share them publicly; a
competition demo is fine as long as participants keep no copies.

What this repo does:

- No clip is committed. TalkBank distributes the corpus, its media rule above covers the
  clips, and this repo's rule is to never commit audio or child data.
- Files made from the corpus (`test-set.csv`, `test-speakers.txt`, the mel cache, a trained
  model) are not shared. If they are adapted material, BY-ND does not allow sharing them, and
  BY-NC-SA allows it only for noncommercial use under the same license. For the model, TalkBank's
  answer above settles it: never public.

## Citation

- Benway et al. (2022), "PERCEPT-R: An Open-Access American English Child/Clinical Speech
  Corpus Specialized for the Audio Classification of /ɹ/", *Proceedings of Interspeech 2022*,
  pp. 3648-3652, doi:10.21437/Interspeech.2022-10785 (the corpus paper)
- Benway et al. (2023), *Journal of Speech, Language, and Hearing Research*,
  doi:10.1044/2023_JSLHR-22-00343
- The PERCEPT-R corpus on TalkBank: doi:10.21415/0JPJ-X403
