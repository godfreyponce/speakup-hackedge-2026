from dataclasses import dataclass


@dataclass(frozen=True)
class AgeNorm:
    watch_from_months: int
    flag_from_months: int
    source: str


# Lexi (SLP), Nov 3 (#24): a failing r at 5 to 6 is an error but not yet expected mastery, so keep an eye on it;
# from 7 it is an error. Watch from 60 months: ASHA's consonant age-of-acquisition chart (Crowe & McLeod 2020),
# r acquired by 5.5 years. Flag from 84: ASHA, gliding remediated by 6 to 7. One rule for every r error.
AGE_NORMS: dict[tuple[str, str], AgeNorm] = {
    ("r", "gliding"): AgeNorm(
        watch_from_months=60,
        flag_from_months=84,
        source="https://www.asha.org/practice-portal/clinical-topics/articulation-and-phonology/selected-phonological-processes/",
    ),
    ("r", "distortion"): AgeNorm(
        watch_from_months=60,
        flag_from_months=84,
        source="https://www.asha.org/siteassets/practice-portal/speech-sound-disorders-articulation-and-phonology/consonant-age-of-acquisition.pdf",
    ),
    ("r", "off"): AgeNorm(
        watch_from_months=60,
        flag_from_months=84,
        source="https://www.asha.org/siteassets/practice-portal/speech-sound-disorders-articulation-and-phonology/consonant-age-of-acquisition.pdf",
    ),
}


def _norm(error_type: str, sound: str) -> AgeNorm:
    norm = AGE_NORMS.get((sound, error_type))
    if norm is None:
        raise ValueError(f"no age norm for sound {sound!r} with error type {error_type!r}")
    return norm


def should_flag(error_type: str | None, sound: str, age_months: int) -> bool:
    return error_type is not None and age_months >= _norm(error_type, sound).flag_from_months


def should_watch(error_type: str | None, sound: str, age_months: int) -> bool:
    if error_type is None:
        return False
    norm = _norm(error_type, sound)
    return norm.watch_from_months <= age_months < norm.flag_from_months


def _years_months(months: int) -> str:
    return f"{months // 12} yr {months % 12} mo"


def explain(error_type: str | None, sound: str, age_months: int) -> str:
    """Why an error is flagged, watched or not, in one sentence for the SLP. Reads the same table as
    should_flag and should_watch, so a change to the norms (Lexi's bands, #24) changes the explanation with it."""
    if error_type is None:
        return ""
    norm = _norm(error_type, sound)
    child, cutoff = _years_months(age_months), _years_months(norm.flag_from_months)
    if age_months >= norm.flag_from_months:
        return f"Flagged: this error is expected to be gone by {cutoff}, and the child is {child}."
    if age_months >= norm.watch_from_months:
        return (f"Not flagged: this error is still common until {cutoff}, and the child is {child}. "
                f"Keep an eye on it: it is worth watching from {_years_months(norm.watch_from_months)}.")
    return f"Not flagged: this error is still common until {cutoff}, and the child is {child}."
