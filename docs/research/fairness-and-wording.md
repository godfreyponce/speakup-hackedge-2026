# Fairness and wording

## How Speak Up describes itself

Speak Up is a **screening and monitoring aid**. It points out sounds for the SLP to check; the SLP
makes every call. It **never diagnoses**. Classrooms include children at risk (autism, Down
syndrome, language or learning delays), so the wording matters *(expert reply, UTD speech
technology professor)*.

Never say: "diagnoses", "detects disorders", "replaces the therapist", or any number we did not
measure ourselves on the board. FDA software-as-a-medical-device rules are another reason to stay a
screening aid.

## An accent is not a disorder

Accents are their own research field, and Speak Up should not try to solve them *(expert reply)*.
Instead:

- **Score only where every dialect agrees:** the r at the start of a word ("red") and word-initial
  /s/. Final-position words become practice only.
- **Never auto-flag "th"** substitutions; they are normal in several dialects.
- **A dialect rule filter after the model** marks known patterns (for example a Spanish tapped r)
  as "may be a dialect difference, please check" instead of an error.
- **Measure the false-alarm rate per accent group**, before and after the filter (Speech Accent
  Archive, CORAAL, Speechocean762).
- Make the processing **depend less on the language**: sound-level features, not English-specific
  patterns *(expert reply)*.
- Bilingual Spanish-English questions (what not to flag, the word list, the Spanish family note)
  are out to two UTD bilingual-language researchers.

## Confidence: the model's honest opinion

- The model outputs a confidence, not just right or wrong. **Calibrate** it, so 70% means right
  about 70% of the time.
- Show it to the SLP, and in the middle band say **"Unsure, SLP please listen"** instead of a
  confident guess.
- Set the flag threshold **once, from the test set**, and never move it to agree with an SLP or a
  child. Moving the line does not change what the model thinks; hiding its confidence would.

## Adult voices

Arti v0 learned only children's voices and misses errors in adult voices (the team's demo voices).

- Plan: pitch-gated voice normalization before the model, plus adult clips in training.
- Look at **vocal effort** too, not only pitch: adults and children differ in it *(expert reply;
  vocal effort is that researcher's field)*. His center has three finished PhDs on vocal effort in
  whispered speech, and the method differs when the microphone applies automatic gain control
  *(expert reply, Nov 15)*: check whether the board's USB mic does, and say so in the report. Which
  papers to read is asked.
