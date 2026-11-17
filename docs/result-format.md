# Result format

What the model hands to the app after it listens to one word (#3). The real model (#2) and the fake one (`speakup/fake_model.py`) both return this, so the app (#5) works with either.

Code: `speakup/result.py`. `check(d)` returns a `Result`, or raises `ValueError` naming every bad field. A record with any field not listed here fails, so a child's name or an audio path can't ride along.

## Fields

| field | type | correct | wrong, and why |
|---|---|---|---|
| `word` | string | `"rabbit"` | `""`: empty |
| `target_sound` | string | `"r"` | `null`: required |
| `expected_phone` | string, IPA | `"ɹ"` | `""`: empty |
| `heard_phone` | string, IPA, or `null` | `"w"` | `"w"` with `error_type: null`: a correct word must be heard as `expected_phone` |
| `error_type` | `"gliding"`, `"distortion"`, `"off"`, or `null` | `"gliding"` | `"stopping"`: not one of the r errors in scope |
| `confidence` | number 0 to 1, or `null` | `0.82` | `1.5`: out of range |
| `model` | string | `"arti-v0"` | `""`: empty |
| `recorded_at` | ISO 8601 with a UTC offset | `"2026-11-05T10:15:00-06:00"` | `"2026-11-05T10:15:00"`: no offset |

`"off"` is a wrong r whose kind the model can't tell. Screens show it as "the r sounded off", and like every r error it is one to keep an eye on from 60 months and flagged from 84 (`speakup/age_norms.py`).

`heard_phone` is `null` when the model can't name what it heard. That is allowed with an error: the model can tell an r came out wrong without naming the sound.

## Two whole records

A glided r:

```json
{"word": "rabbit", "target_sound": "r", "expected_phone": "ɹ", "heard_phone": "w",
 "error_type": "gliding", "confidence": 0.82, "model": "arti-v0",
 "recorded_at": "2026-11-05T10:15:00-06:00"}
```

A correct r:

```json
{"word": "carrot", "target_sound": "r", "expected_phone": "ɹ", "heard_phone": "ɹ",
 "error_type": null, "confidence": 0.91, "model": "arti-v0",
 "recorded_at": "2026-11-05T10:15:20-06:00"}
```

## The fake model

`fake_listen(word, rng)` picks one of three outcomes at random: correct, gliding, or distortion (with `heard_phone: null`). It sets `model` to `"fake"`. Pass `random.Random(seed)` for a repeatable run.

## Tests

```bash
python3 -m unittest
```

The app and the tests use numpy. The board has numpy preinstalled, so the same command works there; on a Mac, run it with a python3 that has numpy.
