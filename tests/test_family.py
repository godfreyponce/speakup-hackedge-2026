import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from speakup import family
from speakup.age_norms import AGE_NORMS
from speakup.result import Result
from speakup.family import build_prompt, check_family, facts, fixed_note, practice_words, qwen_note
from tests.test_summary import FakeModel, _try

# rabbit and red are flagged at 8 yr 0 mo; carrot and tree were said right.
SESSION = [_try("rabbit", "gliding", "w"), _try("carrot"), _try("red", "distortion", None), _try("tree")]
AGE = 96

# Real Qwen2.5-0.5B replies to this module's prompts on the laptop (Nov 14), with the session's words swapped in.
EN = "Today your child said 4 words with the r sound. Please practice rabbit and red at home, slowly and for fun."
ES = "Hoy su hijo o hija dijo 4 palabras con el sonido r. Practiquen rabbit y red en casa, despacio y jugando."


class FamilyFactsTest(unittest.TestCase):
    def test_practice_words_are_flagged_or_watched_words(self):
        self.assertEqual(practice_words(SESSION, AGE), ["rabbit", "red"])
        # Under 5, gliding is normal for age: nothing for the family to practice.
        self.assertEqual(practice_words([_try("rabbit", "gliding", "w")], 59), [])

    def test_facts_hold_the_count_and_words_but_no_verdict(self):
        self.assertEqual(facts(SESSION, AGE, "en"),
                         "Sound: r\nNumber of words tried: 4\nWords to practice: rabbit, red")
        self.assertEqual(facts(SESSION, AGE, "es"),
                         "Sonido: r\nNúmero de palabras dichas: 4\nPalabras para practicar: rabbit, red")

    def test_prompt_ends_with_the_facts(self):
        for lang in family.LANGS:
            with self.subTest(lang):
                p = build_prompt(SESSION, AGE, lang)
                self.assertTrue(p.endswith(f"<|im_start|>user\n{facts(SESSION, AGE, lang)}<|im_end|>\n<|im_start|>assistant\n"))


class CheckFamilyTest(unittest.TestCase):
    def test_passing_notes(self):
        self.assertEqual(check_family("  " + EN + "\n", SESSION, AGE, "en"), EN)
        self.assertEqual(check_family(ES, SESSION, AGE, "es"), ES)

    def test_rejects(self):
        cases = {
            "wrong number": (EN.replace("4 words", "5 words"), "en"),
            "spanish wrong number": (ES.replace("4 palabras", "6 palabras"), "es"),
            "number as a word": (EN.replace("4 words", "four words"), "en"),
            "spanish number as a word": (ES.replace("4 palabras", "cuatro palabras"), "es"),
            "made-up count": (EN + " Practice once a day.", "en"),
            "word said right": (EN.replace("rabbit and red", "rabbit and carrot"), "en"),
            "spanish word said right": (ES.replace("rabbit y red", "rabbit y tree"), "es"),
            "copied example word": (EN.replace("rabbit and red", "rabbit, red and fork"), "en"),
            "diagnose": (EN + " We cannot diagnose your child.", "en"),
            "disorder": (EN + " This is a disorder.", "en"),
            "pass": (EN + " Your child passed.", "en"),
            "refer": (EN + " We refer your child.", "en"),
            "spanish banned word": (ES + " Esto es un trastorno.", "es"),
            "spanish diagnosis": (ES + " No es un diagnóstico.", "es"),
            "english in the spanish slot": (EN, "es"),
            "spanish in the english slot": (ES, "en"),
            "wrong sound": (EN.replace("the r sound", "the b sound"), "en"),
            "spanish wrong sound": (ES.replace("sonido r", "sonido t"), "es"),
            "one word as words": (EN.replace("4 words", "a single word"), "en"),
            "spanish one word as words": (ES.replace("4 palabras", "una sola palabra"), "es"),
            "a practice word left out": (EN.replace("rabbit and red", "rabbit"), "en"),
            "a word repeated": (ES.replace("rabbit y red", "rabbit, red, red y red"), "es"),
            "list word not in the session": (EN.replace("rabbit and red", "rabbit, red and rocket"), "en"),
            "spanish pass": (ES + " Su hijo pasó la prueba.", "es"),
            "spanish refer": (ES + " Recomendamos derivar a su hijo.", "es"),
            "fail": (EN + " Your child failed the screening.", "en"),
            "spanish fail": (ES + " Su hijo falló la prueba.", "es"),
            "spanish fail, suspend": (ES + " Su hijo suspendió la prueba.", "es"),
            "spanish number above twenty": (ES + " Practiquen veinticinco minutos.", "es"),
            "spanish sixteen without the accent": (ES + " Practiquen dieciseis minutos.", "es"),
            "right number, wrong meaning": (EN + " 4 of them need practice.", "en"),
            "quoted wrong sound": (EN.replace("the r sound", "the 'b' sound"), "en"),
            # SESSION has 4 words tried and 2 with errors: the tried count claimed as errors.
            "words wrong": (EN.replace("4 words with the r sound", "4 words wrong"), "en"),
            "missed words": (EN.replace("said 4 words with the r sound", "missed 4 words"), "en"),
            "words with an error": (EN.replace("the r sound", "an error"), "en"),
            "spanish said wrong": (ES.replace("Hoy su hijo o hija dijo", "Su hijo o hija dijo mal"), "es"),
            "spanish with an error": (ES.replace("con el sonido r", "con error"), "es"),
            "spanish had an error": (ES.replace("dijo 4 palabras con el", "tuvo 4 palabras con error en el"), "es"),
            "spanish incorrect": (ES.replace("con el sonido r", "incorrectas"), "es"),
            # Reviewer finds on 8c589b2. A family note names practice words; it never claims errors or negates.
            "colon count, wrong": ("Words your child said wrong today: 4. Please practice rabbit and red at home.", "en"),
            "colon count, error": ("Words with an error today: 4. Please practice rabbit and red at home.", "en"),
            "colon count, missed": ("Words your child missed today: 4. Please practice rabbit and red at home.", "en"),
            "spanish colon count, mal": ("Palabras que su hijo o hija dijo mal hoy: 4. Practiquen rabbit y red en casa.", "es"),
            "spanish colon count, error": ("Palabras con error hoy: 4. Practiquen rabbit y red en casa.", "es"),
            "claim in the next sentence": (EN.replace("with the r sound.", "with the r sound. All of them were wrong."), "en"),
            "spanish claim in the next sentence": (ES.replace("sonido r.", "sonido r. Todas estaban mal."), "es"),
            "spanish erroneous": (ES.replace("con el sonido r", "erróneas"), "es"),
            "spanish difficult": ("Hoy 4 palabras fueron difíciles. Practiquen rabbit y red en casa.", "es"),
            "spanish fallas": (ES.replace("con el sonido r", "con fallas"), "es"),
            "spanish fallos": ("Hoy su hijo o hija tuvo fallos en 4 palabras. Practiquen rabbit y red en casa.", "es"),
            "not right": (EN.replace("said 4 words with the r sound", "did not say 4 words right"), "en"),
            "didn't get right": (EN.replace("said 4 words with the r sound", "didn't get 4 words right"), "en"),
            "spanish not well": (ES.replace("dijo 4 palabras con el sonido r", "no dijo bien 4 palabras"), "es"),
            "sounded off": ("Today 4 words sounded off. Please practice rabbit and red at home.", "en"),
            "struggled": ("Today your child struggled with 4 words. Please practice rabbit and red at home.", "en"),
            "an issue": ("Today 4 words had an issue. Please practice rabbit and red at home.", "en"),
            "spanish costaron": ("Hoy 4 palabras le costaron. Practiquen rabbit y red en casa.", "es"),
            "spanish se trabo": ("Hoy su hijo o hija se trabó en 4 palabras. Practiquen rabbit y red en casa.", "es"),
            "practice count": ("Today 4 words need practice: rabbit and red.", "en"),
            "spanish practice count": ("Hoy 4 palabras necesitan práctica: rabbit y red.", "es"),
            # Second review: the count may sit only in the example's or the fixed note's count sentence.
            "tricky": ("Today 4 words were tricky for your child. Please practice rabbit and red at home, slowly and for fun.", "en"),
            "found hard": (EN.replace("said 4 words", "found 4 words hard"), "en"),
            "spanish complicated": ("Hoy 4 palabras fueron complicadas con el sonido r. Practiquen rabbit y red en casa.", "es"),
            "to work on": ("Today your child has 4 words to work on with the r sound: rabbit and red.", "en"),
            "work on": ("Please work on 4 words at home with the r sound: rabbit and red.", "en"),
            "practise": ("Please practise 4 words at home with the r sound: rabbit and red.", "en"),
            "spanish to work on": ("Hoy su hijo o hija tiene 4 palabras para trabajar con el sonido r: rabbit y red.", "es"),
            "spanish to improve": ("Hoy su hijo o hija tiene 4 palabras para mejorar con el sonido r: rabbit y red.", "es"),
            "spanish review": ("Repasen 4 palabras en casa con el sonido r: rabbit y red.", "es"),
            "said correctly": (EN.replace("4 words with", "4 words correctly with"), "en"),
            "spanish said well": (ES.replace("dijo 4", "dijo bien 4"), "es"),
            "spanish said correctly": (ES.replace("4 palabras con", "4 palabras correctamente con"), "es"),
            "cannot say": (EN.replace("Today your child said", "Your child cannot say").replace("sound.", "sound yet."), "en"),
            "without the sound": (EN.replace("with the r sound", "without the r sound"), "en"),
            "unable to say": (EN.replace("said 4", "was unable to say 4"), "en"),
            "spanish without the sound": (ES.replace("con el sonido r", "sin el sonido r"), "es"),
            # Third review: a sentence that is not the count sentence or a practice line, a quantifier, "cannot".
            "all need practice": ("Today your child said 4 words with the r sound. All of them need practice: rabbit and red.", "en"),
            "spanish all need practice": ("Hoy su hijo o hija dijo 4 palabras con el sonido r. Todas necesitan práctica: rabbit y red.", "es"),
            "spanish all need more practice": ("Hoy su hijo o hija dijo 4 palabras con el sonido r. Todas necesitan más práctica. Practiquen rabbit y red en casa.", "es"),
            "fixed count sentence, all hard": ("Words your child said today with the r sound: 4. All were hard. "
                                               "Please practice rabbit and red at home.", "en"),
            "all hard": ("Today your child said 4 words with the r sound. All of them were hard. Please practice rabbit and red at home, slowly and for fun.", "en"),
            "they were tricky": ("Today your child said 4 words with the r sound. They were tricky, so please practice rabbit and red at home, slowly and for fun.", "en"),
            "spanish all complicated": ("Hoy su hijo o hija dijo 4 palabras con el sonido r. Todas fueron complicadas. Practiquen rabbit y red en casa, despacio y jugando.", "es"),
            "spanish all hard": ("Hoy su hijo o hija dijo 4 palabras con el sonido r. Todas fueron duras. Practiquen rabbit y red en casa.", "es"),
            "practice all of them": ("Today your child said 4 words with the r sound. Please practice all of them at home, especially rabbit and red.", "en"),
            "spanish practice all": ("Hoy su hijo o hija dijo 4 palabras con el sonido r. Practiquen todas en casa, sobre todo rabbit y red.", "es"),
            "cannot say them": ("Today your child said 4 words with the r sound. Your child cannot say them yet, so please practice rabbit and red at home.", "en"),
            "all said without": ("Today your child said 4 words with the r sound. All were said without the r sound. Please practice rabbit and red at home.", "en"),
            "spanish all said without": ("Hoy su hijo o hija dijo 4 palabras con el sonido r. Todas las dijo sin el sonido r. Practiquen rabbit y red en casa.", "es"),
            # Fourth review: a practice line may hold only the practice words and the example's own words.
            "practice the remaining words": ("Today your child said 4 words with the r sound. Please practice rabbit and red at home, then the remaining words.", "en"),
            "practice the words from today": ("Today your child said 4 words with the r sound. Please practice rabbit and red at home, along with the words from today.", "en"),
            "practice the whole list": ("Today your child said 4 words with the r sound. Please practice rabbit and red at home, and the whole list too.", "en"),
            "spanish the other words": ("Hoy su hijo o hija dijo 4 palabras con el sonido r. Practiquen rabbit y red en casa, y también las demás palabras.", "es"),
            "spanish the remaining words": ("Hoy su hijo o hija dijo 4 palabras con el sonido r. Practiquen rabbit y red en casa, y las palabras restantes.", "es"),
            "spanish today's words": ("Hoy su hijo o hija dijo 4 palabras con el sonido r. Practiquen rabbit y red en casa, junto con las palabras de hoy.", "es"),
            "spanish the whole list": ("Hoy su hijo o hija dijo 4 palabras con el sonido r. Practiquen estas palabras en casa, la lista entera: rabbit y red.", "es"),
            # Fifth review: a fixed-note sentence counts only filled in, and only from the note that fits the session.
            "fixed sentence with its placeholder": ("Words your child said today with the r sound: {tried}. Please practice rabbit and red at home.", "en"),
            "fixed practice sentence unfilled": (EN + " Please practice these words at home, slowly and for fun: {words}.", "en"),
            "fixed none closing with practice words": (EN + " Keep talking and reading together at home.", "en"),
            "cut off": (EN.removesuffix("."), "en"),
            "empty": ("  ", "en"),
        }
        for name, (reply, lang) in cases.items():
            with self.subTest(name):
                with self.assertRaises(ValueError):
                    check_family(reply, SESSION, AGE, lang)


class FixedNoteTest(unittest.TestCase):
    def test_file_holds_both_languages(self):
        data = json.loads(family.FIXED_PATH.read_text(encoding="utf-8"))
        for lang in family.LANGS:
            self.assertEqual(set(data[lang]), {"practice", "none"})

    def test_fixed_note_is_filled_by_code(self):
        self.assertEqual(fixed_note(SESSION, AGE, "en"),
                         "Words your child said today with the r sound: 4. Please practice these words at home, "
                         "slowly and for fun: rabbit, red.")
        self.assertIn("rabbit, red", fixed_note(SESSION, AGE, "es"))

    def test_fixed_note_for_r_words_is_unchanged(self):
        # #50 put the sound in the templates; the text for r words must stay as Lexi checked it.
        self.assertEqual(fixed_note(SESSION, AGE, "es"),
                         "Palabras con el sonido r que su hijo o hija dijo hoy: 4. Practiquen estas palabras en casa, "
                         "despacio y jugando: rabbit, red.")
        self.assertEqual(fixed_note([_try("carrot")], AGE, "en"),
                         "Words your child said today with the r sound: 1. Keep talking and reading together at home.")
        self.assertEqual(fixed_note([_try("carrot")], AGE, "es"),
                         "Palabras con el sonido r que su hijo o hija dijo hoy: 1. Sigan hablando y leyendo juntos en casa.")

    def test_count_sentence_names_the_words_sound(self):
        # #50: an /s/ session must not say "the r sound". No /s/ age norm exists yet (Raf's part), so the test adds one.
        sun = [Result(word="sun", target_sound="s", expected_phone="s", heard_phone="θ", error_type="distortion",
                      confidence=0.9, model="fake", recorded_at="2026-11-14T10:00:00-06:00"),
               Result(word="bus", target_sound="s", expected_phone="s", heard_phone="s", error_type=None,
                      confidence=0.9, model="fake", recorded_at="2026-11-14T10:00:00-06:00")]
        norm = AGE_NORMS[("r", "distortion")]
        with mock.patch.dict(AGE_NORMS, {("s", "distortion"): norm}):
            self.assertEqual(fixed_note(sun, AGE, "en"), "Words your child said today with the s sound: 2. "
                                                          "Please practice these words at home, slowly and for fun: sun.")
            self.assertIn("Palabras con el sonido s que", fixed_note(sun, AGE, "es"))
            en = "Today your child said 2 words with the s sound. Please practice sun at home, slowly and for fun."
            es = "Hoy su hijo o hija dijo 2 palabras con el sonido s. Practiquen sun en casa, despacio y jugando."
            for lang, reply in (("en", en), ("es", es), ("en", fixed_note(sun, AGE, "en")), ("es", fixed_note(sun, AGE, "es"))):
                with self.subTest(reply):
                    self.assertEqual(check_family(reply, sun, AGE, lang), reply)
            for lang, reply in (("en", en.replace("the s sound", "the r sound")),
                                ("es", es.replace("sonido s", "sonido r"))):
                with self.subTest(reply), self.assertRaises(ValueError):
                    check_family(reply, sun, AGE, lang)

    def test_fixed_note_passes_its_own_check(self):
        # Guards Lexi's edits to the file: a fixed note with a banned word or a stray number fails here.
        for results, age in ((SESSION, AGE), ([_try("carrot")], AGE), ([_try("rabbit", "gliding", "w")], 59)):
            for lang in family.LANGS:
                with self.subTest(lang=lang, age=age, n=len(results)):
                    text = fixed_note(results, age, lang)
                    self.assertEqual(check_family(text, results, age, lang), text)


class QwenNoteTest(unittest.TestCase):
    def test_qwen_note_is_the_checked_reply(self):
        model = FakeModel(ES)
        self.assertEqual(qwen_note(SESSION, AGE, "es", model), ES)
        self.assertEqual(model.prompts, [build_prompt(SESSION, AGE, "es")])

    def test_wrong_reply_raises(self):
        with self.assertRaises(ValueError):
            qwen_note(SESSION, AGE, "en", FakeModel("Your child passed."))

    def test_no_words_to_practice_skips_qwen(self):
        model = FakeModel(EN)
        with self.assertRaises(ValueError):
            qwen_note([_try("carrot")], AGE, "en", model)
        self.assertEqual(model.prompts, [])


class SamplesTest(unittest.TestCase):
    def test_script_writes_ten_samples_without_the_model(self):
        from scripts import note_samples
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "samples.txt"
            with contextlib.redirect_stdout(io.StringIO()):
                note_samples.main([str(out)])
            text = out.read_text(encoding="utf-8")
        self.assertEqual(text.count("=== Sample "), 10)
        self.assertEqual(text.count("Family note, fixed (es): "), 10)
        self.assertNotIn("by Qwen", text)


if __name__ == "__main__":
    unittest.main()
