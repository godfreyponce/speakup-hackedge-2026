"""What the sound book's computer-made pictures say, sound by sound and speaker group by speaker group.

Each picture is one item (a sound in a simple frame: vowels in /hVd/ like Hillenbrand et al. 1995, consonants
between two /ɑ/ vowels, /r/ also in "rabbit") said by one speaker group. This module turns an item and a group into a
synthesizer plan (speakup.synth) plus the list of target values it used, each marked "measured" (taken from a
published table for that group) or "estimated" (with how it was estimated). The pictures are drawn offline by
scripts/build_synth_pictures.py; the server uses this module to make the sound on request for the Play button, so no
audio file is ever stored.

Where values come from:
- Vowel F0, F1, F2, F3 for men, women, and boys and girls 10 to 12: Hillenbrand et al. (1995), from the norms file.
- 6-year-olds: no reachable table (Lee et al. 1999 is behind a paywall), so the 10 to 12 values are raised by 10%
  for a vocal tract assumed about 10% shorter (vocal tract length scaling, Vorperian et al. 2009; Fitch and Giedd
  1999 found no boy-girl difference in tract length before puberty). F0 277 Hz: age 6 in Maturo et al. (2012), as
  given by a secondary normative sheet (UNVERIFIED).
- /r w l j/: adult means of Espy-Wilson (1992, 2 men and 2 women, pooled), scaled to each group by how that group's
  Hillenbrand vowels compare with the pooled adult vowels. Children's /r/ F3: McAllister Byun and Hitchcock (2012),
  correct tokens of children 6 to 11. R vowel /ɝ/ at 6: the F3-F2 gap of Flipsen et al. (2001).
- Stops: VOT of Lisker and Abramson (1964) as reported by Kim (2021); burst shapes from the book's place table.
- Fricative noise peaks: Todd et al. (2011), Wong and Munson (2025) for children; the 6 to 8 kHz /s/ and 2.5 to 4 kHz
  /ʃ/ adult ranges of Jongman et al. (2000).
- Nasal murmur and antiformant: Kent and Read (2002) textbook ranges (UNVERIFIED), /m/ zero near Mehta et al. (2012).
- Error versions (lisps, derhotacized r, hypernasality) follow the book's descriptions; they illustrate the pattern
  and are always marked estimated."""

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from speakup.synth import OFF, Plan, Seg

NORMS_PATH = Path(__file__).with_name("data") / "formant_norms.json"
CHILD6_SCALE = 1.10
CHILD6_F0 = 277.0

# Sources this feature adds to the book's reference list (the rest are already in it).
EXTRA_REFS = {
    "klatt1980": {"text": "Klatt, D. H. (1980). Software for a cascade/parallel formant synthesizer. Journal of the "
                          "Acoustical Society of America, 67(3), 971-995.", "doi": "10.1121/1.383940"},
    "klatt1990": {"text": "Klatt, D. H., & Klatt, L. C. (1990). Analysis, synthesis, and perception of voice quality "
                          "variations among female and male talkers. Journal of the Acoustical Society of America, "
                          "87(2), 820-857.", "doi": "10.1121/1.398894"},
}


@dataclass(frozen=True)
class Group:
    id: str
    label: str
    age: str  # "6", "10-12" or "adult"
    sex: str  # "female" or "male"
    age_months: tuple  # (lo, hi), hi None = open
    estimated: bool  # its vowel values are estimated, not measured

    @property
    def age_label(self) -> str:
        return {"6": "6 years", "10-12": "10 to 12 years", "adult": "Adult"}[self.age]

    @property
    def sex_label(self) -> str:
        if self.age == "adult":
            return "Woman" if self.sex == "female" else "Man"
        return "Girl" if self.sex == "female" else "Boy"


GROUPS = (
    Group("girl6", "Girl, 6 years", "6", "female", (72, 95), True),
    Group("boy6", "Boy, 6 years", "6", "male", (72, 95), True),
    Group("girl10", "Girl, 10 to 12 years", "10-12", "female", (120, 155), False),
    Group("boy10", "Boy, 10 to 12 years", "10-12", "male", (120, 155), False),
    Group("woman", "Adult woman", "adult", "female", (216, None), False),
    Group("man", "Adult man", "adult", "male", (216, None), False),
)
GROUP = {g.id: g for g in GROUPS}
DOC_GROUPS = ("boy6", "girl10", "woman", "man")  # the compact grid in the Word document

HVD_VOWELS = ("i", "ɪ", "eɪ", "ɛ", "æ", "ɑ", "ɔ", "oʊ", "ʊ", "u", "ʌ")


@dataclass
class Value:
    what: str  # "F2 of /ɹ/", "VOT", "noise peak"
    hz: float  # Hz, or ms for durations (unit says which)
    status: str  # "measured" or "estimated"
    source: list  # reference keys
    how: str = ""  # for an estimate: how it was made; for a measured value: which table
    unit: str = "Hz"


@dataclass
class Built:
    plan: Plan
    values: list = field(default_factory=list)
    marks: list = field(default_factory=list)  # (kind, value, seg index, label)
    top_hz: int = 6000

    @property
    def estimated(self) -> bool:
        return any(v.status == "estimated" for v in self.values)

    @property
    def reasons(self) -> list[str]:
        return list(dict.fromkeys(v.how for v in self.values if v.status == "estimated" and v.how))

    @property
    def sources(self) -> list[str]:
        return list(dict.fromkeys(k for v in self.values for k in v.source))


# ---------------------------------------------------------------- data from the norms file

@lru_cache(maxsize=2)
def _norms(path: str = str(NORMS_PATH)) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def hillenbrand(ph: str, age: str, sex: str) -> dict | None:
    """Hillenbrand et al. (1995) means for a vowel: {F0, F1, F2, F3}; age "10-12" or "adult"."""
    lo = 120 if age == "10-12" else 216
    for n in _norms()["norms"]:
        if (n["phoneme"] == ph and n["source"] == "hillenbrand1995" and n["sex"] == sex
                and n["age_min_months"] == lo):
            return {"F0": n["extra"]["F0"]["mean"], "F1": n["F1"]["mean"], "F2": n["F2"]["mean"], "F3": n["F3"]["mean"]}
    return None


def flipsen_gap(age_months: int, sex: str) -> float | None:
    for n in _norms()["norms"]:
        if (n["phoneme"] == "ɝ" and n["source"] == "flipsen2001" and n["sex"] == sex
                and n["age_min_months"] <= age_months <= n["age_max_months"]):
            return n["F3_F2"]["mean"]
    return None


@lru_cache(maxsize=None)
def scale(gid: str) -> tuple[float, float, float]:
    """How a group's formants compare with the pooled adult (men and women) ones, F1 to F3, averaged over the 11
    Hillenbrand /hVd/ vowels. Used to carry an adult pooled value (Espy-Wilson 1992) to each group."""
    g = GROUP[gid]
    base = g.age if g.age != "6" else "10-12"
    out = []
    for k in ("F1", "F2", "F3"):
        ratios = []
        for v in HVD_VOWELS:
            m, w, x = hillenbrand(v, "adult", "male"), hillenbrand(v, "adult", "female"), hillenbrand(v, base, g.sex)
            ratios.append(x[k] / ((m[k] + w[k]) / 2))
        r = sum(ratios) / len(ratios)
        out.append(r * (CHILD6_SCALE if g.age == "6" else 1.0))
    return tuple(out)


def high(gid: str) -> tuple[float, float]:
    """F4 and F5: an adult man's 3500 and 4500 Hz (Klatt 1980's defaults are similar) scaled like F3."""
    s3 = scale(gid)[2] / scale("man")[2]
    return 3500 * s3, 4500 * s3


def bw(gid: str) -> tuple:
    k = 1.0 if GROUP[gid].age == "adult" else 1.2
    return tuple(round(b * k) for b in (80, 100, 140, 250, 300))


def group_f0(gid: str) -> tuple[float, Value]:
    g = GROUP[gid]
    if g.age == "6":
        return CHILD6_F0, Value("Voice pitch (F0), mean", CHILD6_F0, "estimated", ["maturo2012"],
                                "F0 for age 6 from Maturo et al. (2012) as given by a secondary normative sheet "
                                "(UNVERIFIED against the paper)")
    vals = [hillenbrand(v, g.age, g.sex)["F0"] for v in HVD_VOWELS]
    f0 = round(sum(vals) / len(vals))
    return f0, Value("Voice pitch (F0), mean", f0, "measured", ["hillenbrand1995"], "mean over the /hVd/ vowels")


SIX_HOW = ("6-year-old vowels are not in a reachable table: the 10 to 12 year values raised by 10% for a shorter "
           "vocal tract (vocal tract length scaling)")
SCALED_HOW = "adult pooled mean (2 men, 2 women) carried to this group by vocal tract scaling from its vowels"


def vowel(ph: str, gid: str) -> tuple[tuple, list[Value], float]:
    """F1..F5, the values used, and the vowel's own F0."""
    g = GROUP[gid]
    h4, h5 = high(gid)
    base = "10-12" if g.age == "6" else g.age
    if ph == "ə":  # no published schwa values: the centre of the group's vowel space
        vs = [hillenbrand(v, base, g.sex) for v in HVD_VOWELS]
        f = [sum(v[k] for v in vs) / len(vs) * (CHILD6_SCALE if g.age == "6" else 1) for k in ("F1", "F2", "F3")]
        vals = [Value(f"{k} of /ə/", round(x), "estimated", ["hillenbrand1995"],
                      "no published schwa values: the average of the group's 11 Hillenbrand vowels (the centre of "
                      "its vowel space)") for k, x in zip(("F1", "F2", "F3"), f)]
        f0 = group_f0(gid)[0]
        return (f[0], f[1], f[2], h4, h5), vals, f0
    h = hillenbrand(ph, base, g.sex)
    if g.age == "6":
        f = [h[k] * CHILD6_SCALE for k in ("F1", "F2", "F3")]
        vals = [Value(f"{k} of /{ph}/", round(x), "estimated", ["hillenbrand1995", "vorperian2009"], SIX_HOW)
                for k, x in zip(("F1", "F2", "F3"), f)]
        f0 = CHILD6_F0
    else:
        f = [h[k] for k in ("F1", "F2", "F3")]
        vals = [Value(f"{k} of /{ph}/", round(x), "measured", ["hillenbrand1995"], "Hillenbrand et al. 1995 group mean")
                for k, x in zip(("F1", "F2", "F3"), f)]
        f0 = h["F0"]
    return (f[0], f[1], f[2], max(h4, f[2] + 500), max(h5, f[2] + 1400)), vals, f0


# Adult pooled means, Espy-Wilson (1992), Hz.
ESPY = {
    ("w", "pre"): (381, 848, 2320), ("l", "pre"): (399, 1074, 2553), ("ɹ", "pre"): (419, 1285, 1779),
    ("j", "pre"): (317, 2142, 2827), ("w", "inter"): (349, 771, 2340), ("l", "inter"): (445, 1060, 2640),
    ("ɹ", "inter"): (460, 1240, 1720), ("j", "inter"): (361, 2270, 2920),
}
CHILD_R_F3 = 2266  # McAllister Byun and Hitchcock (2012), correct onset r, ages 6;0 to 11;9, pooled
DERHOT_CHILD_F3 = 2950  # middle of the 2700 to 3200 Hz the book cites for derhotacized r (McAllister Byun 2012)


def approximant(ph: str, where: str, gid: str, derhot: bool = False, next_f3: float | None = None):
    g = GROUP[gid]
    s = scale(gid)
    base = ESPY[(ph, where)]
    f = [base[i] * s[i] for i in range(3)]
    vals = []
    for i, k in enumerate(("F1", "F2", "F3")):
        vals.append(Value(f"{k} of /{ph}/", round(f[i]), "estimated", ["espywilson1992"], SCALED_HOW))
    if ph == "ɹ" and g.age != "adult" and where == "pre":
        f[2] = CHILD_R_F3
        vals[2] = Value("F3 of /ɹ/", CHILD_R_F3, "measured", ["mcallister2012"],
                        "children 6 to 11 years, both sexes, onset r tokens rated correct (children in r therapy)")
    if derhot:
        if g.age != "adult":
            f[2] = DERHOT_CHILD_F3
            how = "middle of the 2700 to 3200 Hz range the book cites for derhotacized r in school-age children"
            src = ["mcallister2012"]
        else:
            f[2] = (f[2] + (next_f3 or f[2] * 1.4)) / 2
            how = "illustration: halfway between a correct r F3 and the next vowel's F3"
            src = ["espywilson1992", "hillenbrand1995"]
        f[1] = f[1] * 0.95
        vals = [Value("F1 of the r attempt", round(f[0]), "estimated", ["espywilson1992"], SCALED_HOW),
                Value("F2 of the r attempt", round(f[1]), "estimated", ["espywilson1992"],
                      "illustration: a correct r F2, a little lower (lip rounding)"),
                Value("F3 of the r attempt", round(f[2]), "estimated", src, how)]
    h4, h5 = high(gid)
    return (f[0], f[1], f[2], h4, h5), vals


# Consonant loci into /ɑ/ for the pooled adult (where formants start for each place), Hz. Modelling choices that
# follow the book's place table (alveolar F2 near 1700 to 1800 Hz; labial F2 below the vowel; velar F2 and F3 close).
LOCI = {"lab": (300, 900, 2200), "alv": (300, 1750, 2700), "vel": (300, 1600, 1950), "pal": (300, 1900, 2500)}


def locus(place: str, gid: str):
    s = scale(gid)
    h4, h5 = high(gid)
    return tuple(LOCI[place][i] * s[i] for i in range(3)) + (h4, h5)


VOT = {"p": 58, "t": 70, "k": 80, "b": 1, "d": 5, "ɡ": 21}  # ms, Lisker and Abramson 1964 via Kim 2021
PLACE = {"p": "lab", "b": "lab", "m": "lab", "f": "lab", "v": "lab", "t": "alv", "d": "alv", "n": "alv", "s": "alv",
         "z": "alv", "θ": "alv", "ð": "alv", "l": "alv", "k": "vel", "ɡ": "vel", "ŋ": "vel", "ʃ": "pal", "ʒ": "pal",
         "tʃ": "pal", "dʒ": "pal", "j": "pal", "ɹ": "alv", "w": "lab", "h": "alv"}


def burst(place: str, gid: str) -> tuple:
    """Parallel resonators of a stop release: labial diffuse and falling, alveolar diffuse and rising, velar compact
    (one mid peak near the vowel's F2 and F3). Shapes from the book's place table; frequencies scale like F3."""
    k = scale(gid)[2] / scale("man")[2]
    shapes = {
        "lab": ((700, 800, 0), (1500, 1200, -6), (3000, 2000, -14)),
        "alv": ((3500, 1500, -8), (4800, 1800, 0), (6200, 2000, 0)),
        "vel": ((1650, 350, 0), (3300, 900, -16)),
        "pal": ((2600, 800, -2), (3600, 1000, 0), (5200, 2000, -8)),
    }
    return tuple((round(f * k), round(b * k), db) for f, b, db in shapes[place])


# Fricative noise peaks by group, Hz, with their status.
def fric_peak(ph: str, gid: str) -> Value:
    g = GROUP[gid]
    if ph in ("s", "z"):
        table = {
            "6": (7700, "estimated", ["todd2011"], "Todd et al. (2011) spectral mean for children about 5 years (7699 "
                  "Hz), used as the peak"),
            "10-12": (7400, "estimated", ["todd2011", "jongman2000"], "no table for 10 to 12: between the about-5-year "
                      "value (Todd et al. 2011) and the adult 6 to 8 kHz range"),
            "adult": ((6500 if g.sex == "male" else 7300), "estimated", ["jongman2000"],
                      "inside the verified adult 6 to 8 kHz range (Jongman et al. 2000); the exact value and the higher "
                      "value for women are assumptions"),
        }
    else:
        table = {
            "6": (4600, "estimated", ["wong2025", "todd2011"], "between Wong and Munson (2025, 4558 Hz peak at 2;6 to "
                  "3;6) and Todd et al. (2011, 5223 Hz spectral mean at about 5)"),
            "10-12": (4000, "estimated", ["todd2011", "jongman2000"], "no table for 10 to 12: between the young-child "
                      "values and the adult 2.5 to 4 kHz range"),
            "adult": ((3000 if g.sex == "male" else 3500), "estimated", ["jongman2000"],
                      "inside the verified adult 2.5 to 4 kHz range (Jongman et al. 2000); the exact value is an "
                      "assumption"),
        }
    hz, st, src, how = table[g.age]
    return Value(f"Noise peak of /{ph}/", hz, st, src, how)


def fric_shape(kind: str, peak: float, gid: str) -> tuple[tuple, float]:
    """(resonators, bypass dB) for a fricative noise. kind: s, sh, flat, interdental, dental, lateral, palatal."""
    k = scale(gid)[2] / scale("man")[2]
    if kind == "s":
        return ((peak, peak * 0.22, 0), (peak * 1.3, 2500, -12), (peak * 0.68, 1400, -12)), OFF
    if kind == "sh":
        return ((peak, peak * 0.22, 0), (peak * 1.7, 1500, -16), (peak * 2.4, 2500, -24)), OFF
    if kind == "flat":
        return ((7500 * min(k, 1.3), 6000, -10),), -14
    if kind == "interdental":
        return ((7000 * min(k, 1.3), 5000, -6),), -10
    if kind == "dental":
        return ((peak, peak * 0.35, 0), (peak * 1.3, 3000, -12)), -20
    if kind == "lateral":
        return ((peak, 1800, 0), (1600 * k, 900, -12), (peak * 2, 3000, -24)), OFF
    if kind == "palatal":
        return ((peak, peak * 0.2, 0), (peak * 1.5, 2000, -8)), OFF
    raise ValueError(kind)


# ---------------------------------------------------------------- items

@dataclass(frozen=True)
class Item:
    id: str
    sound: str  # IPA of the sound the picture is about
    context: str  # the frame, in IPA, as shown ("hɑd", "ɑsɑ", "ɹæbɪt")
    word: str  # plain words ("hod", "a-sa", "rabbit")
    kind: str  # vowel, r-vowel, diphthong, approximant, stop, fricative, affricate, nasal, error
    title: str
    top_hz: int = 6000
    error_of: str = ""  # for an error version: the item it is a wrong version of


VOWEL_WORDS = {"i": ("heed", "snd-iy"), "ɪ": ("hid", "snd-ih"), "eɪ": ("hayed", "snd-ey"), "ɛ": ("head", "snd-eh"),
               "æ": ("had", "snd-ae"), "ɑ": ("hod", "snd-aa"), "ɔ": ("hawed", "snd-ao"), "oʊ": ("hoed", "snd-ow"),
               "ʊ": ("hood", "snd-uh"), "u": ("who'd", "snd-uw"), "ʌ": ("hud", "snd-ah")}
VOWEL_IDS = {"i": "iy", "ɪ": "ih", "eɪ": "ey", "ɛ": "eh", "æ": "ae", "ɑ": "aa", "ɔ": "ao", "oʊ": "ow", "ʊ": "uh",
             "u": "uw", "ʌ": "ah"}
CONS = {  # id, top Hz, kind
    "p": ("p", 8000, "stop"), "b": ("b", 8000, "stop"), "t": ("t", 8000, "stop"), "d": ("d", 8000, "stop"),
    "k": ("k", 8000, "stop"), "ɡ": ("g", 8000, "stop"),
    "f": ("f", 11000, "fricative"), "v": ("v", 11000, "fricative"), "θ": ("th", 11000, "fricative"),
    "ð": ("dh", 11000, "fricative"), "s": ("s", 11000, "fricative"), "z": ("z", 11000, "fricative"),
    "ʃ": ("sh", 11000, "fricative"), "ʒ": ("zh", 11000, "fricative"), "h": ("h", 6000, "fricative"),
    "tʃ": ("ch", 11000, "affricate"), "dʒ": ("jh", 11000, "affricate"),
    "m": ("m", 6000, "nasal"), "n": ("n", 6000, "nasal"), "ŋ": ("ng", 6000, "nasal"),
    "w": ("w", 6000, "approximant"), "l": ("l", 6000, "approximant"), "ɹ": ("r", 6000, "approximant"),
    "j": ("y", 6000, "approximant"),
}


def _items() -> list[Item]:
    out = []
    for ph, (word, _) in VOWEL_WORDS.items():
        out.append(Item(f"v-{VOWEL_IDS[ph]}", ph, f"h{ph}d", word, "vowel", f'/{ph}/ in "{word}"'))
    out.append(Item("v-schwa", "ə", "ədɑ", "a-dah", "vowel", '/ə/ in "a-dah"'))
    out.append(Item("v-er", "ɝ", "hɝd", "heard", "r-vowel", '/ɝ/ in "heard"'))
    for ph, word in (("aɪ", "hide"), ("aʊ", "how'd"), ("ɔɪ", "hoyd")):
        out.append(Item(f"v-{ {'aɪ': 'ay', 'aʊ': 'aw', 'ɔɪ': 'oy'}[ph]}", ph, f"h{ph}d", word, "diphthong",
                        f'/{ph}/ in "{word}"'))
    for ph, (cid, top, kind) in CONS.items():
        ctx = f"ɑ{ph}ɑ" if ph != "h" else "ɑhɑ"
        out.append(Item(f"c-{cid}", ph, ctx, f"a-{cid}a" if cid != "y" else "a-ya", kind, f"/{ph}/ in /{ctx}/", top))
    out.append(Item("w-rabbit", "ɹ", "ɹæbɪt", "rabbit", "approximant", '/ɹ/ in "rabbit"'))
    out.append(Item("e-wabbit", "w", "wæbɪt", "wabbit", "error", '"rabbit" said as "wabbit" (gliding)', 6000,
                    "w-rabbit"))
    out.append(Item("e-rabbit-derhot", "ɹ", "ɹ̠æbɪt", "rabbit (distorted r)", "error",
                    '"rabbit" with a derhotacized (distorted) r', 6000, "w-rabbit"))
    for kind, title in (("interdental", "Interdental lisp"), ("dental", "Dentalized /s/"),
                        ("lateral", "Lateral lisp"), ("palatal", "Palatal /s/")):
        out.append(Item(f"e-s-{kind}", "s", "ɑsɑ", f"a-sa ({title.lower()})", "error", f"/ɑsɑ/ with a {title.lower()}"
                        if "lisp" in title else f"/ɑsɑ/ said as a {title.lower()}", 11000, "c-s"))
    out.append(Item("e-had-nasal", "æ", "hæd", "had (hypernasal)", "error", '"had" with hypernasality', 6000, "v-ae"))
    return out


ITEMS = {i.id: i for i in _items()}

# Which pictures each book section shows. Error sections show pairs: (target, what the child says).
SECTION_ITEMS = {
    **{sec: [f"v-{VOWEL_IDS[ph]}"] for ph, (_, sec) in VOWEL_WORDS.items()},
    "snd-schwa": ["v-schwa"], "snd-diphthongs": ["v-ay", "v-aw", "v-oy"],
    "snd-r": ["w-rabbit", "c-r", "v-er"], "snd-w": ["c-w"], "snd-l": ["c-l"], "snd-j": ["c-y"],
    "snd-approx-compare": ["c-r", "c-w", "c-l", "c-y"],
    "snd-p": ["c-p"], "snd-b": ["c-b"], "snd-t": ["c-t"], "snd-d": ["c-d"], "snd-k": ["c-k"], "snd-g": ["c-g"],
    "snd-s": ["c-s"], "snd-z": ["c-z"], "snd-sh": ["c-sh"], "snd-zh": ["c-zh"], "snd-f": ["c-f"], "snd-v": ["c-v"],
    "snd-th": ["c-th"], "snd-dh": ["c-dh"], "snd-h": ["c-h"], "snd-ch": ["c-ch"], "snd-jh": ["c-jh"],
    "snd-m": ["c-m"], "snd-n": ["c-n"], "snd-ng": ["c-ng"],
}
SECTION_PAIRS = {
    "snd-r-errors": [("w-rabbit", "e-wabbit"), ("w-rabbit", "e-rabbit-derhot")],
    "err-gliding": [("w-rabbit", "e-wabbit")],
    "err-derhotacization": [("w-rabbit", "e-rabbit-derhot")],
    "err-vocalic-r": [("v-er", "v-ah")],
    "err-stopping": [("c-s", "c-t")],
    "err-fronting": [("c-k", "c-t")],
    "err-backing": [("c-t", "c-k")],
    "err-deaffrication": [("c-ch", "c-sh")],
    "err-voicing": [("c-p", "c-b")],
    "err-lisp-interdental": [("c-s", "e-s-interdental")],
    "err-lisp-dentalized": [("c-s", "e-s-dental")],
    "err-lisp-lateral": [("c-s", "e-s-lateral")],
    "err-lisp-palatal": [("c-s", "e-s-palatal")],
    "err-hypernasality": [("v-ae", "e-had-nasal")],
    "err-hyponasality": [("c-m", "c-b")],
}
# The item for a phoneme in context mode (/book?word=...).
PHONEME_ITEM = {**{ph: f"v-{VOWEL_IDS[ph]}" for ph in VOWEL_WORDS}, "ə": "v-schwa", "ɝ": "v-er", "ɚ": "v-er",
                "aɪ": "v-ay", "aʊ": "v-aw", "ɔɪ": "v-oy", "e": "v-ey", "o": "v-ow", "g": "c-g",
                **{ph: f"c-{cid}" for ph, (cid, _, _) in CONS.items()}}


def group_for(age_months: int | None, sex: str | None = None) -> list[str]:
    """Group ids for a child: the band covering the age, else the nearest older band (age_band); both sexes unless
    the sex is known (girl first). No age: every group."""
    age = age_band(age_months)[0] if age_months is not None else None
    out = [g.id for g in GROUPS if (age is None or g.age == age) and (sex in (None, "") or g.sex == sex)]
    return out


# Error versions by name, for a query such as lookup("gliding", ...).
VARIANTS = {"gliding": "e-wabbit", "derhotacized": "e-rabbit-derhot", "interdental": "e-s-interdental",
            "dentalized": "e-s-dental", "lateral": "e-s-lateral", "palatal": "e-s-palatal",
            "hypernasal": "e-had-nasal"}


def home_section(item_id: str) -> str | None:
    """The book section an item belongs to (an error version: its error section)."""
    for sec, pairs in SECTION_PAIRS.items():
        if sec.startswith("err-") and any(p[1] == item_id for p in pairs) and ITEMS[item_id].kind == "error":
            return sec
    for sec, items in SECTION_ITEMS.items():
        if item_id in items:
            return sec
    return None


def confusable(item_id: str, book: dict | None = None) -> list[str]:
    """Items to compare with: the book's "Often confused with" sections of the item's home section (their first
    picture), then the error versions of this sound, or for an error version its target."""
    if book is None:
        from speakup import book as book_mod
        book = book_mod.load()
    sec = home_section(item_id)
    by_id = {s["id"]: s for s in book["sections"]}
    out = []
    item = ITEMS[item_id]
    if item.error_of:
        out.append(item.error_of)
    for other in by_id.get(sec, {}).get("confused_with", []):
        for cand in SECTION_ITEMS.get(other, [])[:1] + [p[1] for p in SECTION_PAIRS.get(other, [])]:
            out.append(cand)
    out += [i.id for i in ITEMS.values() if i.error_of and ITEMS[i.error_of].sound == item.sound
            and item.kind != "error"]
    return [i for i in dict.fromkeys(out) if i != item_id]


def lookup(sound: str, sex: str | None = None, age_months: int | None = None, age: str | None = None) -> dict | None:
    """The picture for a phoneme ("ɹ", "s"), an item id ("w-rabbit") or an error variant ("gliding"), for a sex
    ("female"/"male", default female) and an age in months (or an age band "6", "10-12", "adult").
    Returns {"item", "group", "file", "age_band", "fallback"}: fallback is True when no band covers the age and the
    nearest older band was used (or no age was given). None when there is no picture for that sound."""
    item = sound if sound in ITEMS else VARIANTS.get(sound) or PHONEME_ITEM.get(sound)
    if item is None:
        return None
    if age is not None:
        band, fallback = age, False
    else:
        band, fallback = age_band(age_months)
    sex = sex if sex in ("female", "male") else "female"
    group = next(g.id for g in GROUPS if g.age == band and g.sex == sex)
    return {"item": item, "group": group, "file": picture_name(item, group), "age_band": band, "fallback": fallback}


# ---------------------------------------------------------------- plans

def open_glottis(B: tuple) -> tuple:
    """Bandwidths while the glottis is open (aspiration): F1 is damped and broad (Klatt 1980 widens B1 too)."""
    return (max(B[0], 400), B[1] + 80, B[2] + 100, B[3], B[4])


def _hvd(gid: str, F: tuple, f0: float, vowel_segs: list[Seg]) -> list[Seg]:
    B = bw(gid)
    d = locus("alv", gid)
    return ([Seg("h", 70, F, open_glottis(B), ah=42, ramp=12)] + vowel_segs
            + [Seg("d", 55, d, B, av=36, trans=45, lead=0.6, ramp=10),
               Seg("", 12, d, B, af=44, fric=burst("alv", gid), ramp=0, trans=0, label="")])


def _frame_vowel(gid: str) -> tuple[tuple, float]:
    F, _, f0 = vowel("ɑ", gid)
    return F, f0


def build(item_id: str, gid: str) -> Built:
    item, g = ITEMS[item_id], GROUP[gid]
    B = bw(gid)
    f0, f0v = group_f0(gid)
    values: list[Value] = []
    marks: list = []
    a_F, _ = _frame_vowel(gid)
    a_vals = vowel("ɑ", gid)[1]

    def mark_formants(idx: int, F: tuple):
        for i in range(3):
            marks.append((f"F{i + 1}", round(F[i]), idx, f"F{i + 1} {round(F[i]):,}"))

    if item.kind in ("vowel", "r-vowel", "diphthong") and item.id != "v-schwa":
        if item.kind == "diphthong":
            a, b = {"aɪ": ("ɑ", "ɪ"), "aʊ": ("ɑ", "ʊ"), "ɔɪ": ("ɔ", "ɪ")}[item.sound]
            Fa, va, f0 = vowel(a, gid)
            Fb, vb, _ = vowel(b, gid)
            how = ("no published values for this diphthong were read: it glides from the group's /{}/ to its /{}/ "
                   "(Hillenbrand monophthongs)".format(a, b))
            for v in va + vb:
                v.status, v.how = "estimated", how
                v.what = v.what.replace(f"/{a}/", f"start (/{a}/)").replace(f"/{b}/", f"end (/{b}/)")
            values += va + vb
            segs = _hvd(gid, Fa, f0, [Seg(a, 110, Fa, B, av=60, ah=30, trans=0, ramp=15, focus=True, label=item.sound),
                                      Seg("", 90, Fb, B, av=58, ah=30, trans=90, ramp=0, label=""),
                                      Seg(b, 80, Fb, B, av=57, ah=30, trans=0, ramp=0, focus=True, label="")])
            for i in range(3):  # both ends are marked; one label per formant says where it starts and ends
                marks.append((f"F{i + 1}", round(Fa[i]), 1, ""))
                marks.append((f"F{i + 1}", round(Fb[i]), 3, f"F{i + 1} {round(Fa[i]):,}\nto {round(Fb[i]):,}"))
        elif item.kind == "r-vowel":
            F, vals, f0 = _er(gid)
            values += vals
            segs = _hvd(gid, F, f0, [Seg("ɝ", 250, F, B, av=60, ah=30, trans=0, ramp=15, focus=True)])
            mark_formants(1, F)
        else:
            F, vals, f0 = vowel(item.sound, gid)
            values += vals
            vsegs = [Seg(item.sound, 250, F, B, av=60, ah=30, trans=0, ramp=15, focus=True)]
            if item.sound in ("eɪ", "oʊ"):  # measured at the steady state; a short offglide follows
                off = vowel("ɪ" if item.sound == "eɪ" else "ʊ", gid)[0]
                mid = tuple((x + y) / 2 for x, y in zip(F, off))
                vsegs = [Seg(item.sound, 190, F, B, av=60, ah=30, trans=0, ramp=15, focus=True),
                         Seg("", 70, mid, B, av=56, ah=30, trans=60, ramp=0)]
            segs = _hvd(gid, F, f0, vsegs)
            mark_formants(1, F)
        values.append(Value("Voice pitch (F0)", round(f0), "estimated" if g.age == "6" else "measured",
                            ["maturo2012"] if g.age == "6" else ["hillenbrand1995"],
                            group_f0(gid)[1].how if g.age == "6" else "Hillenbrand et al. 1995, this vowel"))
        return Built(Plan(segs, f0, seed=_seed(item_id, gid)), values, marks, item.top_hz)

    if item.id == "v-schwa":
        F, vals, _ = vowel("ə", gid)
        values += vals + [f0v]
        d = locus("alv", gid)
        segs = [Seg("ə", 90, F, B, av=56, ah=30, ramp=15, focus=True), Seg("d", 50, d, B, av=36, trans=40, lead=1.0),
                Seg("", 10, d, B, af=44, fric=burst("alv", gid), ramp=0, trans=0),
                Seg("ɑ", 230, a_F, B, av=60, ah=30, trans=45)]
        mark_formants(0, F)
        return Built(Plan(segs, f0, seed=_seed(item_id, gid)), values, marks, item.top_hz)

    if item.id == "e-had-nasal":
        F, vals, f0 = vowel("æ", gid)
        k = scale(gid)[0]
        fnp, fnz = 350 * k, 650 * k
        values += vals + [Value("Extra nasal peak", round(fnp), "estimated", ["chen1997"],
                                "illustration: inside the 250 to 450 Hz nasal peak range of Chen (1997), scaled to "
                                "the group"),
                          Value("Nasal antiresonance (dip)", round(fnz), "estimated", ["chen1997", "klatt1980"],
                                "illustration: a modelling choice that weakens F1, as in Klatt (1980) nasalization")]
        Bn = (B[0] + 80,) + B[1:]
        segs = _hvd(gid, F, f0, [Seg("æ̃", 250, F, Bn, av=60, ah=30, trans=0, ramp=15, focus=True,
                                     nasal=(fnp, 120, fnz, 150))])
        mark_formants(1, F)
        marks.append(("nasal", round(fnp), 1, f"nasal {round(fnp):,}"))
        return Built(Plan(segs, f0, seed=_seed(item_id, gid)), values, marks, item.top_hz)

    if item.id in ("w-rabbit", "e-wabbit", "e-rabbit-derhot"):
        Fae, vae, f0ae = vowel("æ", gid)
        Fih, vih, _ = vowel("ɪ", gid)
        if item.id == "e-wabbit":
            C, cvals = approximant("w", "pre", gid)
            name = "w"
        else:
            C, cvals = approximant("ɹ", "pre", gid, derhot=item.id == "e-rabbit-derhot", next_f3=Fae[2])
            name = "ɹ" if item.id == "w-rabbit" else "ɹ̠"
        values += cvals + [Value(v.what, v.hz, v.status, v.source, v.how) for v in vae]
        lab, alv = locus("lab", gid), locus("alv", gid)
        segs = [Seg(name, 75, C, B, av=58, ramp=20, focus=True, label=name),
                Seg("æ", 140, Fae, B, av=60, ah=30, trans=70, lead=0.1),
                Seg("b", 65, lab, B, av=40, trans=40, lead=1.0, ramp=8),
                Seg("", 8, lab, B, af=38, fric=burst("lab", gid), ramp=0, trans=0),
                Seg("ɪ", 95, Fih, B, av=58, ah=30, trans=40),
                Seg("t", 70, alv, B, trans=40, lead=1.0, ramp=8),
                Seg("", 10, alv, B, af=50, fric=burst("alv", gid), ramp=0, trans=0),
                Seg("", 45, alv, B, ah=46, ramp=0, trans=0, label="")]
        mark_formants(0, C)
        return Built(Plan(segs, f0, seed=_seed(item_id, gid)), values, marks, item.top_hz)

    # Consonants between two /ɑ/ vowels.
    ph = item.sound
    values += [Value(v.what, v.hz, v.status, v.source, v.how) for v in a_vals]
    values.append(f0v)
    first = Seg("ɑ", 160, a_F, B, av=60, ah=30, ramp=15)
    last = lambda trans=45: Seg("ɑ", 230, a_F, B, av=60, ah=30, trans=trans)  # noqa: E731
    place = PLACE.get(ph, "alv")
    L = locus(place, gid)

    if item.kind == "approximant":
        C, cvals = approximant(ph, "inter", gid)
        values = cvals + values
        segs = [first, Seg(ph, 100, C, B, av=57, trans=50, lead=0.5, ramp=20, focus=True), last(60)]
        mark_formants(1, C)
        if ph == "l":  # the abrupt edges of /l/: a fast release
            segs[2] = last(25)
    elif item.kind == "stop":
        voiced = ph in "bdɡ"
        vot = VOT[ph]
        values.insert(0, Value("Voice onset time (VOT)", vot, "measured" if g.age == "adult" else "estimated",
                               ["lisker1964", "kim2021"],
                               "adult VOT (Lisker and Abramson 1964, as reported by Kim 2021) used for this child "
                               "group; children's VOT is more variable" if g.age != "adult" else
                               "adult mean, Lisker and Abramson (1964) as reported by Kim (2021)", "ms"))
        # A voiced stop between vowels keeps a weak voice bar for part of its closure, then the voicing stops
        # and starts again a few ms after the release (short-lag VOT, the usual English /b d g/).
        closure = ([Seg(ph, 45, L, B, av=40, trans=45, lead=1.0, ramp=8, label=ph),
                    Seg("", 30, L, B, trans=0, ramp=10, label="")] if voiced else
                   [Seg(ph, 75, L, B, trans=45, lead=1.0, ramp=8, label=ph)])
        segs = [first, *closure,
                Seg("", 9 if not voiced else 6, L, B, af=(50 if not voiced else 44) + (5 if place == "vel" else 0), fric=burst(place, gid), ramp=0,
                    trans=0, label="", focus=True)]
        if vot > 3:
            segs.append(Seg("", vot - (9 if not voiced else 6) if vot > 12 else vot, L, open_glottis(B), ah=54 if not voiced else 44,
                            ramp=0, trans=0, label=""))
        segs.append(Seg("ɑ", 230, a_F, B, av=60, ah=30, trans=45, ramp=4))
        marks.append(("vot", vot, 1 + len(closure), f"VOT {vot} ms"))
        marks.append(("burst", 0, 1 + len(closure), "burst"))
    elif item.kind == "nasal":
        k2 = scale(gid)[1]
        zero = {"m": 1000, "n": 1800, "ŋ": 3200}[ph] * k2
        murmur = (270 * scale(gid)[0], L[1], L[2], L[3], L[4])
        values = [Value(f"Murmur low resonance of /{ph}/", round(murmur[0]), "estimated", ["kentread2002"],
                        "textbook murmur first resonance about 250 to 300 Hz (Kent and Read 2002, UNVERIFIED), scaled "
                        "to the group"),
                  Value(f"Antiformant (zero) of /{ph}/", round(zero), "estimated",
                        ["kentread2002"] + (["mehta2012"] if ph == "m" else []),
                        "textbook range (Kent and Read 2002, UNVERIFIED)" + ("; near the 1100 Hz of Mehta et al. "
                                                                            "(2012)" if ph == "m" else "")
                        + ", scaled to the group")] + values
        Bm = (B[0] + 40, B[1] + 100, B[2] + 100, B[3], B[4])
        segs = [first, Seg(ph, 85, murmur, Bm, av=50, trans=12, lead=0.5, ramp=4, focus=True,
                           nasal=(zero * 1.15, 300, zero, 120)), last(30)]
        marks.append(("murmur", round(murmur[0]), 1, f"murmur {round(murmur[0]):,}"))
        marks.append(("zero", round(zero), 1, f"zero {round(zero):,}"))
    elif item.kind in ("fricative", "error") and ph in ("s", "z", "ʃ", "ʒ", "f", "v", "θ", "ð"):
        voiced = ph in "zʒvð"
        variant = item.id.removeprefix("e-s-") if item.kind == "error" else ""
        if ph in "szʃʒ":
            pv = fric_peak("s" if ph in "sz" else "ʃ", gid)
            peak = pv.hz
            if variant:
                shift = {"interdental": 1.0, "dental": 0.85, "lateral": 0.45, "palatal": 0.68}[variant]
                peak = pv.hz * shift
                desc = {"interdental": "flat, weak noise with no strong peak (direction from Jongman et al. 2000; "
                                       "lisp spectra UNVERIFIED)",
                        "dental": "a lower, flatter peak than a good /s/ (UNVERIFIED)",
                        "lateral": "a lower, diffuse peak with some low-frequency energy (UNVERIFIED)",
                        "palatal": "the peak moved down toward the /ʃ/ range (the book flags a child /s/ peak below "
                                   "5 to 6 kHz)"}[variant]
                pv = Value("Noise peak of the s attempt" if variant != "interdental" else "Noise (no clear peak)",
                           round(peak), "estimated", pv.source + (["li2009"] if variant == "palatal" else []),
                           "illustration: " + desc)
            values.insert(0, pv)
            kind = variant or ("s" if ph in "sz" else "sh")
        else:
            kind, peak = "flat", 0
            values.insert(0, Value(f"Noise of /{ph}/", 0, "estimated", ["jongman2000"],
                                   "flat, weak noise with no dominant peak (Jongman et al. 2000; the about 7 to 8 kHz "
                                   "values are UNVERIFIED)", "none"))
        fr, byp = fric_shape(kind, peak, gid)
        level = {"s": 56, "sh": 57, "palatal": 55, "dental": 54, "lateral": 53, "interdental": 46, "flat": 44}[kind]
        if voiced:
            level -= 6
        dur = 140 if not voiced else 110
        segs = [first, Seg(ph, dur, L, B, af=level, fric=fr, bypass=byp + level - 60 if byp > OFF else OFF,
                           av=46 if voiced else OFF, trans=40, lead=0.5, ramp=18, focus=True, label=ph), last(40)]
        if peak and kind != "interdental":
            marks.append(("peak", round(peak), 1, f"peak {round(peak):,}"))
    elif ph == "h":
        values.insert(0, Value("/h/ noise shaped by the next vowel's formants", 0, "measured", ["hillenbrand1995"],
                               "aspiration through the /ɑ/ formants", "none"))
        segs = [first, Seg("h", 90, a_F, open_glottis(B), ah=54, trans=0, ramp=15, focus=True), last(0)]
    elif item.kind == "affricate":
        voiced = ph == "dʒ"
        pv = fric_peak("ʃ", gid)
        values.insert(0, Value("Noise peak of the /ʃ/ part", pv.hz, pv.status, pv.source, pv.how))
        fr, _ = fric_shape("sh", pv.hz, gid)
        segs = [first, Seg(ph[0], 60, L, B, av=36 if voiced else OFF, trans=45, lead=1.0, ramp=8, label=ph[0]),
                Seg(ph[1], 85 if not voiced else 60, L, B, af=60 if not voiced else 54, fric=fr,
                    av=44 if voiced else OFF, trans=0, ramp=0, focus=True, label=ph[1]), last(40)]
        marks.append(("peak", pv.hz, 2, f"peak {pv.hz:,}"))
    else:
        raise ValueError(item_id)
    return Built(Plan(segs, f0, seed=_seed(item_id, gid)), values, marks, item.top_hz)


def _er(gid: str):
    g = GROUP[gid]
    if g.age != "6":
        return vowel("ɝ", gid)
    h = hillenbrand("ɝ", "10-12", g.sex)
    gap = flipsen_gap(72, g.sex)
    f1, f2 = h["F1"] * CHILD6_SCALE, h["F2"] * CHILD6_SCALE
    f3 = f2 + gap
    h4, h5 = high(gid)
    vals = [Value("F1 of /ɝ/", round(f1), "estimated", ["hillenbrand1995", "vorperian2009"], SIX_HOW),
            Value("F2 of /ɝ/", round(f2), "estimated", ["hillenbrand1995", "vorperian2009"], SIX_HOW),
            Value("F3 of /ɝ/", round(f3), "estimated", ["flipsen2001"],
                  f"the estimated F2 plus the measured F3-F2 gap at age 6 ({round(gap)} Hz, Flipsen et al. 2001)")]
    return (f1, f2, f3, max(h4, f3 + 600), max(h5, f3 + 1500)), vals, CHILD6_F0


def _seed(item_id: str, gid: str) -> int:
    import zlib
    return zlib.crc32(f"{item_id}|{gid}".encode())


def picture_name(item_id: str, gid: str) -> str:
    return f"{item_id}-{gid}.png"


def audio(item_id: str, gid: str):
    """The synthesized samples (48 kHz floats) for an item and group: what the Play button plays."""
    from speakup import synth
    return synth.synthesize(build(item_id, gid).plan)


# One or two plain sentences per picture: what an SLP should look for. Taken from the book's own descriptions.
LOOK_FOR = {
    "v-iy": "F1 very low and F2 very high, close under F3. The highest F2 of any vowel.",
    "v-ih": "Like /i/ but a little more open: F1 a bit higher and F2 a bit lower than in /i/.",
    "v-ey": "F1 mid and F2 high, gliding up toward /ɪ/ at the end.",
    "v-eh": "F1 mid to high and F2 fairly high: between /ɪ/ and /æ/.",
    "v-ae": "F1 high and F2 fairly high, wide apart from F1. The jaw is open.",
    "v-aa": "F1 highest of all vowels and F2 low, so F1 and F2 sit close together near the bottom.",
    "v-ao": "F1 high and F2 low, both a little lower than in /ɑ/ (rounded lips).",
    "v-ow": "F1 mid and F2 low, gliding lower toward /ʊ/ at the end.",
    "v-uh": "F1 fairly low and F2 low to mid: like /u/ but more open.",
    "v-uw": "F1 low and F2 low (rounded lips, back tongue), F3 well above.",
    "v-ah": "F1 mid to high and F2 in the middle: a central vowel with F3 at its normal height.",
    "v-schwa": "A short, weak vowel with formants near the middle of the speaker's range.",
    "v-er": "F3 held low, close to F2, through the whole vowel. The key r sign.",
    "v-ay": "A glide from /ɑ/ (F1 high, F2 low) to /ɪ/ (F1 low, F2 high): F2 rises steeply.",
    "v-aw": "A glide from /ɑ/ to /ʊ/: F1 and F2 both fall.",
    "v-oy": "A glide from /ɔ/ (F2 low) to /ɪ/ (F2 high): F2 rises steeply.",
    "c-r": "F3 dips low toward F2 between the vowels, then rises again. F2 stays moderate, not very low.",
    "w-rabbit": "At the start, F3 is low and close to F2, then rises into the vowel. A narrow F3-F2 gap is the sign of a good r.",
    "c-w": "F1 and F2 both very low (F2 lower than in /u/) while F3 stays high: a very wide F3-F2 gap.",
    "c-l": "F3 stays high, far above F2, and the bands start and stop abruptly at the edges.",
    "c-y": "F1 very low and F2 very high, near /i/, gliding into the vowel.",
    "c-p": "Silence, a weak burst spread over low frequencies, then a long stretch of aspiration noise before voicing (long VOT).",
    "c-b": "A weak voice bar in the closure, a weak burst, and voicing almost at once after it (short VOT).",
    "c-t": "Silence, a burst strongest at high frequencies, then aspiration before voicing (long VOT).",
    "c-d": "A short voice bar, a high-frequency burst, and voicing right after it (short VOT). F2 starts near 1700 to 1800 Hz in adults.",
    "c-k": "A burst with one compact mid-frequency peak; F2 and F3 start close together (the velar pinch). Long VOT.",
    "c-g": "Like /k/ (compact mid-frequency burst, F2 and F3 close) but with a short VOT.",
    "c-f": "Faint, flat noise across the whole range with no strong band. Easy to miss.",
    "c-v": "Faint, flat noise like /f/ with a voice bar underneath.",
    "c-th": "Faint, flat noise like /f/: the picture alone cannot tell /θ/ from /f/.",
    "c-dh": "Faint, flat noise with voicing, often very short.",
    "c-s": "Strong noise that starts above about 3 to 4 kHz and is darkest high up, for a child often above 6 kHz.",
    "c-z": "Like /s/ (strong high noise) with a voice bar at the bottom.",
    "c-sh": "Strong noise with a clear lower edge and its peak in the middle range (about 2.5 to 5 kHz), lower than /s/.",
    "c-zh": "Like /ʃ/ (mid-range noise peak) with a voice bar at the bottom.",
    "c-h": "Noise with the next vowel's formant bands already in it, and no voice bar.",
    "c-ch": "Silence, a burst, then /ʃ/-like noise that starts abruptly.",
    "c-jh": "A short voice bar, a burst, then short /ʃ/-like noise with voicing.",
    "c-m": "A weak, smooth murmur with energy only at the bottom (about 250 to 350 Hz) and sharp edges into the vowels.",
    "c-n": "Like /m/: a low murmur with sharp edges. The place shows mainly in the vowel transitions.",
    "c-ng": "A low murmur like /m/ and /n/; F2 and F3 come together at the vowel edge as for /k/ and /g/.",
    "e-wabbit": "Gliding: F3 stays high at the start instead of dipping, F2 is very low, and the F3-F2 gap is very wide.",
    "e-rabbit-derhot": "Distorted r: F3 drops only part of the way, so the gap is between a good r and a [w].",
    "e-s-interdental": "Interdental lisp: weak, flat noise like /θ/, with no strong dark band high up.",
    "e-s-dental": "Dentalized /s/: the noise peak is a little lower and flatter than a good /s/.",
    "e-s-lateral": "Lateral lisp: the noise peak is low (about 3 to 4 kHz) and spread out, closer to /ʃ/ than to /s/.",
    "e-s-palatal": "Palatal /s/: the noise peak moves down toward the /ʃ/ range, below about 5 to 6 kHz in a child.",
    "e-had-nasal": "Hypernasality: an extra low nasal band under F1, and F1 weaker and wider than in the oral vowel.",
}

# Age bands the pictures cover, in months. A child between bands gets the nearest older band (flagged).
AGE_BANDS = (("6", 72, 95), ("10-12", 120, 155), ("adult", 216, None))


def age_band(age_months: int | None) -> tuple[str, bool]:
    """The picture age band for a child, and whether it is a fallback (no band covers the age: the nearest older band
    is used, since older children's values are the closest published ones)."""
    if age_months is None:
        return "6", True
    for band, lo, hi in AGE_BANDS:
        if age_months >= lo and (hi is None or age_months <= hi):
            return band, False
    for band, lo, _ in AGE_BANDS:
        if lo > age_months:
            return band, True
    return "adult", True
