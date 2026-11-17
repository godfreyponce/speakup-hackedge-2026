import unittest

from speakup.demo_model import DEMO_OUTCOMES, demo_listen
from speakup.result import Result, check
from speakup.summary import EXAMPLE_FACTS, INSTRUCTIONS, build_prompt, check_reply, note, pass_or_refer


def _try(word, error_type=None, heard_phone="ɹ"):
    return Result(word=word, target_sound="r", expected_phone="ɹ", heard_phone=heard_phone,
                  error_type=error_type, confidence=0.9, model="fake",
                  recorded_at="2026-11-05T10:15:00-06:00")


SESSION = [
    _try("rabbit", "gliding", "w"),
    _try("carrot"),
    _try("red", "distortion", None),
    _try("tree"),
    _try("mirror", "gliding", "w"),
]

DEMO = [check(demo_listen(w)) for w in DEMO_OUTCOMES]  # the --demo script: rabbit gliding, carrot distortion, truck gliding

S1 = [_try("rabbit", "off", None), _try("carrot"), _try("red", "off", None), _try("tree"), _try("mirror", "gliding", "w")]
CLEAN = [_try("carrot"), _try("tree")]

# Real Qwen2.5-0.5B replies from the planning session (plan "What the planning session measured").
S1_AT_96 = ("The child tried 5 words with the r sound. Rabbit had the r sounded off, which is flagged for age. "
            "Red had the r sounded off, which is flagged for age. Mirror had the gliding (heard w), which is flagged for age.")
# DEMO_AT_96 re-measured Nov 3 with truck (#10). DEMO_AT_62 is the giraffe-list reply with the word swapped: with truck, the reply at 62 is correct.
DEMO_AT_96 = ("The child tried 10 words with the r sound. Rabbit had gliding (heard w), which is flagged for age. "
              "Carrot had a distortion, which is flagged for age. Truck had gliding (heard w), which is flagged for age.")
# #28: "very" is a correctly said list word, used here as plain English.
DEMO_VERY_AT_96 = ("The child tried 10 words with the r sound. Rabbit had gliding (heard w), which is flagged for age. "
                   "Carrot had a distortion, which is flagged for age. Truck had gliding (heard w), which is very clearly flagged for age.")
DEMO_AT_62 = ("The child tried 10 words with the r sound. Rabbit had gliding (heard w), which is flagged for age. "
              "Carrot had a distortion, which is normal for age. Truck had gliding (heard w), which is flagged for age.")
SESSION_AT_66 = ("The child tried 5 words with the r sound. Rabbit had gliding (heard w), so keep an eye on it. "
                 "Red had a distortion, so keep an eye on it. Mirror had gliding (heard w), so keep an eye on it.")
SESSION_AT_90 = ("The child tried 5 words with the r sound. Rabbit had gliding (heard w), so flagged for age. "
                 "Red had a distortion, so flagged for age. Mirror had gliding (heard w), so flagged for age.")
CLEAN_AT_90 = "The child tried 2 words with the r sound. There were no errors heard."
COPIED_EXAMPLE = "The child tried 2 words with the r sound. Rope had gliding (heard w), which is normal for age. Bird had no error."
CORRECT_WORD_AS_ERROR = ("The child tried 2 words with the r sound. On carrot, the r came out as t, which is normal at this age. "
                         "Tree had no errors heard.")
WRONG_COUNT = ("The child tried 3 words with the r sound. On rabbit, the r sounded off, flagged for age. "
               "On red, the r sounded off, flagged for age. On mirror, the r sounded off, flagged for age.")


class FakeModel:
    def __init__(self, reply):
        self.reply = reply
        self.prompts = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        return self.reply


class SummaryTest(unittest.TestCase):
    def test_prompt_holds_the_facts(self):
        p = build_prompt(SESSION, 90)
        last = p.split("<|im_start|>user\n")[-1]
        for fact in ["Child's age: 7 yr 6 mo", "Number of words tried: 5",
                     "- rabbit: gliding (heard w), flagged for age", "- red: distortion, flagged for age",
                     "- mirror: gliding (heard w), flagged for age"]:
            self.assertIn(fact, last)
        self.assertNotIn("carrot", last)
        self.assertNotIn("tree", last)
        self.assertNotIn("None", p)
        self.assertTrue(p.startswith("<|im_start|>system\n" + INSTRUCTIONS + "<|im_end|>\n"))
        self.assertTrue(p.endswith("<|im_end|>\n<|im_start|>assistant\n"))

    def test_off_reads_sounded_off(self):
        p = build_prompt([_try("rabbit", "off", None)], 96)
        self.assertIn("rabbit: the r sounded off, flagged for age", p)
        self.assertNotIn(": off", p)

    def test_prompt_with_no_errors(self):
        self.assertIn("Words with an error heard: none<|im_end|>", build_prompt(CLEAN, 90))
        self.assertEqual(pass_or_refer(CLEAN, 90), "Pass: 0 of 2 words flagged for age 7 yr 6 mo.")

    def test_refer_line_with_no_model(self):
        self.assertEqual(pass_or_refer(SESSION, 90),
                         "Refer: 3 of 5 words flagged for age 7 yr 6 mo (rabbit, red, mirror).")

    def test_watch_line_with_no_model(self):
        self.assertEqual(pass_or_refer(SESSION, 80),
                         "Watch: 3 of 5 words to keep an eye on for age 6 yr 8 mo (rabbit, red, mirror).")

    def test_watch_facts(self):
        last = build_prompt(SESSION, 66).split("<|im_start|>user\n")[-1]
        for fact in ["Child's age: 5 yr 6 mo", "- rabbit: gliding (heard w), keep an eye on it",
                     "- red: distortion, keep an eye on it", "- mirror: gliding (heard w), keep an eye on it"]:
            self.assertIn(fact, last)

    def test_normal_facts_under_five(self):
        self.assertIn("- rabbit: gliding (heard w), normal for age",
                      build_prompt(SESSION, 59).split("<|im_start|>user\n")[-1])
        self.assertEqual(pass_or_refer(SESSION, 59), "Pass: 0 of 5 words flagged for age 4 yr 11 mo.")

    def test_example_agrees_with_age_rule(self):
        example = [_try("rope", "gliding", "w"), _try("bird", "distortion", None), _try("carrot"), _try("tree")]
        last = build_prompt(example, 66).split("<|im_start|>user\n")[-1]
        self.assertEqual(last.split("<|im_end|>")[0], EXAMPLE_FACTS)

    def test_check_accepts_true_replies(self):
        self.assertEqual(check_reply(S1_AT_96, S1, 96), S1_AT_96)
        self.assertEqual(check_reply(DEMO_AT_96, DEMO, 96), DEMO_AT_96)
        self.assertEqual(check_reply(DEMO_VERY_AT_96, DEMO, 96), DEMO_VERY_AT_96)
        self.assertEqual(check_reply("  " + CLEAN_AT_90 + "\n", CLEAN, 90), CLEAN_AT_90)
        self.assertEqual(check_reply(SESSION_AT_66, SESSION, 66), SESSION_AT_66)
        self.assertEqual(check_reply(SESSION_AT_90, SESSION, 90), SESSION_AT_90)

    def test_check_rejects_wrong_claims(self):
        cases = {
            "wrong verdict": (DEMO_AT_62, DEMO, 62),
            "watched called flagged": (SESSION_AT_90, SESSION, 66),
            "flagged called keep an eye": (SESSION_AT_66, SESSION, 90),
            "watched called normal": (SESSION_AT_66.replace("so keep an eye on it", "which is normal for age"), SESSION, 66),
            "copied example word": (COPIED_EXAMPLE, CLEAN, 90),
            "correct word named": (CORRECT_WORD_AS_ERROR, CLEAN, 90),
            "wrong count": (WRONG_COUNT, S1, 96),
            "wrong error type": (WRONG_COUNT.replace("3 words", "5 words"), S1, 96),
            "pass or refer": ("The child said most words well. Pass.", S1, 96),
            "empty": ("  \n", S1, 96),
            "denies the errors": (CLEAN_AT_90.replace("2 words", "5 words"), S1, 96),
            "no word flagged": ("No word was flagged for age.", S1, 96),
            "negated verdict": (S1_AT_96.replace("Red had the r sounded off, which is flagged",
                                                 "Red had the r sounded off, which is not flagged"), S1, 96),
            "word not in the session": (DEMO_AT_96 + " Giraffe had gliding (heard w), which is flagged for age.", DEMO, 96),
            "correct word as subject": (DEMO_AT_96 + " Very was said clearly.", DEMO, 96),
            "second word has a different error": ("Rabbit and red had gliding (heard w), so flagged for age.", SESSION, 90),
            "claim with no word": (DEMO_AT_96 + " The word had gliding (heard w), which is flagged for age.", DEMO, 96),
        }
        for name, (reply, results, age) in cases.items():
            with self.subTest(name):
                with self.assertRaises(ValueError):
                    check_reply(reply, results, age)

    def test_check_rejects_a_number_written_as_a_word(self):
        with self.assertRaises(ValueError):
            check_reply(S1_AT_96.replace("5 words", "five words"), S1, 96)

    def test_check_ties_each_number_to_its_fact(self):
        # SESSION at 90 months is 7 yr 6 mo with 5 words: 7 and 6 are in the facts, but they are not the count.
        for reply in (SESSION_AT_90.replace("5 words", "7 words"), SESSION_AT_90.replace("5 words", "6 words"),
                      SESSION_AT_90 + " The child is 6 yr 6 mo.", SESSION_AT_90 + " Try 5 more."):
            with self.subTest(reply), self.assertRaises(ValueError):
                check_reply(reply, SESSION, 90)
        aged = SESSION_AT_90 + " The child is 7 yr 6 mo."
        self.assertEqual(check_reply(aged, SESSION, 90), aged)

    def test_check_rejects_the_tried_count_claimed_as_errors(self):
        # SESSION has 5 words tried and 3 with errors: "5 words" with an error claim says all 5 were wrong.
        for reply in (SESSION_AT_90 + " 5 words had an error.", SESSION_AT_90 + " The child missed 5 words.",
                      SESSION_AT_90 + " 5 words were wrong.", SESSION_AT_90 + " 5 words had errors.",
                      SESSION_AT_90.replace("tried 5 words", "missed 5 words"),
                      # Reviewer finds on 8c589b2: the claim in the next sentence, other error words.
                      SESSION_AT_90 + " The child tried 5 words. All were wrong.", SESSION_AT_90 + " 5 words were erroneous.",
                      SESSION_AT_90 + " 5 words sounded off.", SESSION_AT_90 + " 5 words were off.",
                      SESSION_AT_90 + " The child struggled with 5 words.", SESSION_AT_90 + " 5 words had issues.",
                      SESSION_AT_90 + " 5 words were inaccurate.", SESSION_AT_90 + " 5 words were distorted.",
                      SESSION_AT_90.replace("The child tried", "The child stumbled on"),
                      # Second review: the count sentence must be "The child tried N words with the r sound." exactly.
                      SESSION_AT_90.replace("so flagged for age. Red", "as did all 5 words. Red"),
                      SESSION_AT_90 + " Mirror had gliding (heard w); in all, 5 words were flagged for age.",
                      SESSION_AT_90 + " Rabbit had gliding (heard w), and 5 words were hard for the child.",
                      SESSION_AT_90 + " The child said 5 words correctly.",
                      SESSION_AT_90 + " The child cannot say 5 words with the r sound yet.",
                      # Third review: a quantifier or a negation in another sentence points back at the count.
                      SESSION_AT_90 + " All of them were hard to say.", SESSION_AT_90 + " All were tricky.",
                      SESSION_AT_90 + " Every word needs work.",
                      SESSION_AT_90 + " Rabbit had gliding (heard w), as did all the other words.",
                      SESSION_AT_90 + " Rabbit had gliding (heard w), and every word had an error.",
                      SESSION_AT_90 + " Mirror had gliding (heard w); in all, every word was flagged for age.",
                      SESSION_AT_90 + " The child cannot say the r sound in them yet.",
                      # Fourth review: "only", group words, and "word" outside the count sentence.
                      SESSION_AT_90 + " Rabbit was the only word with an error.", SESSION_AT_90 + " Rabbit had the only error.",
                      SESSION_AT_90 + " Rabbit alone had an error.", SESSION_AT_90 + " Rabbit was the only flagged word.",
                      SESSION_AT_90 + " The words were hard to say.", SESSION_AT_90 + " These words were hard for the child.",
                      SESSION_AT_90 + " The whole list was hard for the child.", SESSION_AT_90 + " Half the words were hard to say.",
                      SESSION_AT_90 + " The majority were hard to say.",
                      SESSION_AT_90 + " Rabbit had an error; so did the remaining words."):
            with self.subTest(reply), self.assertRaises(ValueError):
                check_reply(reply, SESSION, 90)

    def test_each_sentence_is_an_allowed_sentence(self):
        # Fifth review on adfcc28: open wording let a note call a word with an error correct, say "only" by another
        # word, or close with "nothing else". Each sentence must now be one of the note's allowed sentences.
        flagged = SESSION_AT_90.split(". Red")[0] + "."  # count sentence and the rabbit sentence
        for reply in (flagged + " Red was said correctly.", flagged + " Red and mirror were correct.",
                      flagged + " Red sounded right.",
                      flagged + " Rabbit was the single error heard.", flagged + " Rabbit was the lone error.",
                      flagged + " Rabbit was solely flagged for age.",
                      flagged + " Except for rabbit, the r sound was clear.",
                      flagged + " Apart from rabbit, the r sound was clear.",
                      flagged + " Besides rabbit, the child said the r sound clearly.",
                      flagged + " Nothing else stood out.", flagged.removesuffix(".") + ", and that was it.",
                      flagged.removesuffix(".") + ", and nothing else.", flagged + " The r sound was clear otherwise.",
                      SESSION_AT_90.replace("(heard w), so flagged for age. Red", "(heard t), so flagged for age. Red")):
            with self.subTest(reply), self.assertRaises(ValueError):
                check_reply(reply, SESSION, 90)

    def test_allowed_sentences_from_real_notes(self):
        # Forms Qwen wrote in the Nov 14 samples: no "so" before the verdict, "the r sounded off", no "(heard x)".
        results = [_try("truck", "off", None), _try("bear"), _try("car", "off", None)]
        reply = ("The child tried 3 words with the r sound. Truck had the r sounded off, flagged for age. "
                 "Car had the r sounded off, so flagged for age.")
        self.assertEqual(check_reply(reply, results, 102), reply)

    def test_check_rejects_a_note_that_leaves_out_a_flagged_word(self):
        # #50: the Refer line names rabbit, red and mirror; a note naming two of them hides the third from the SLP.
        without_mirror = SESSION_AT_90.split(" Mirror had")[0]
        with self.assertRaises(ValueError):
            check_reply(without_mirror, SESSION, 90)
        # Named only in a listen sentence, mirror's error is still left out.
        with self.assertRaises(ValueError):
            check_reply(without_mirror + " Mirror needs the SLP to listen.", SESSION, 90, ["mirror"])

    def test_check_accepts_a_note_that_leaves_out_a_word_to_keep_an_eye_on(self):
        # A real Qwen2.5-0.5B note (#50 measurement, Nov 14): carrot, kept an eye on at 5 yr 7 mo, is left out.
        # Only words flagged for age must be named; see the proposal on #50's PR.
        results = [_try("bear", "gliding", "w"), _try("rabbit", "distortion", None), _try("rocket", "distortion", None),
                   _try("very", "gliding", "w"), _try("carrot", "distortion", None), _try("car", "gliding", "w"),
                   _try("door")]
        reply = ("The child tried 7 words with the r sound. Bear had gliding (heard w), so keep an eye on it. "
                 "Rabbit had a distortion, so keep an eye on it. Rocket had a distortion, so keep an eye on it. "
                 "Very had gliding (heard w), so keep an eye on it. Car had gliding (heard w), so keep an eye on it.")
        self.assertEqual(check_reply(reply, results, 67), reply)

    def test_check_rejects_an_error_claim_in_a_clean_session(self):
        self.assertEqual(check_reply(CLEAN_AT_90, CLEAN, 90), CLEAN_AT_90)
        with self.assertRaises(ValueError):
            check_reply("The child tried 2 words with the r sound. All were wrong.", CLEAN, 90)
        for extra in (" Both were hard to say.", " Both words had errors, and none were said right."):
            with self.subTest(extra), self.assertRaises(ValueError):
                check_reply("The child tried 2 words with the r sound." + extra, CLEAN, 90)

    def test_check_rejects_a_count_from_the_age_or_zero(self):
        # At 8 yr 0 mo, 8 and 0 are in the facts but are not the count of 2 words.
        results = [_try("rabbit", "gliding", "w"), _try("carrot")]
        good = "The child tried 2 words with the r sound. Rabbit had gliding (heard w), so flagged for age."
        self.assertEqual(check_reply(good, results, 96), good)
        for wrong in ("8 words", "0 words"):
            with self.subTest(wrong), self.assertRaises(ValueError):
                check_reply(good.replace("2 words", wrong), results, 96)

    def test_check_bans_what_the_family_note_bans(self):
        for extra in (" This is a sign of a speech disorder.", " Rabbit failed.", " Rabbit falló."):
            with self.subTest(extra), self.assertRaises(ValueError):
                check_reply(SESSION_AT_90 + extra, SESSION, 90)

    def test_check_rejects_disorder(self):
        with self.assertRaises(ValueError):
            check_reply(SESSION_AT_90 + " Rabbit had gliding (heard w), a disorder.", SESSION, 90)

    def test_check_rejects_a_wrong_sound(self):
        with self.assertRaises(ValueError):
            check_reply(S1_AT_96.replace("the r sound", "the t sound"), S1, 96)

    def test_check_counts_a_word_as_one(self):
        with self.assertRaises(ValueError):
            check_reply(S1_AT_96.replace("5 words", "a single word"), S1, 96)

    def test_listen_words_are_the_words_in_the_unsure_band(self):
        from unittest import mock
        from speakup.session import Attempt
        from speakup.summary import listen_words
        from speakup.words import Word
        tries = [Attempt(Word(r.word, "start"), r, False, False) for r in SESSION]  # confidence 0.9 on each
        # p(wrong) is 0.9 for the errors (rabbit, red, mirror) and 0.1 for the rest.
        self.assertEqual(listen_words(tries), [])
        with mock.patch("speakup.calibration.UNSURE_BAND", (0.05, 0.2)):
            self.assertEqual(listen_words(tries), ["carrot", "tree"])

    def test_listen_words_go_in_the_facts(self):
        last = build_prompt(SESSION, 90, ["carrot"]).split("<|im_start|>user\n")[-1]
        self.assertIn("SLP please listen: carrot<|im_end|>", last)
        self.assertNotIn("SLP please listen", build_prompt(SESSION, 90))

    def test_check_lets_a_listen_word_be_named_without_a_claim(self):
        reply = SESSION_AT_90 + " Carrot needs the SLP to listen."
        self.assertEqual(check_reply(reply, SESSION, 90, ["carrot"]), reply)
        with self.assertRaises(ValueError):
            check_reply(reply, SESSION, 90)
        with self.assertRaises(ValueError):
            check_reply(SESSION_AT_90 + " Carrot had gliding (heard w), so flagged for age.", SESSION, 90, ["carrot"])
        # Review of the allow-list: the listen sentence must name a listen word, not any word.
        for extra, listen in ((" Banana needs the SLP to listen.", []), (" Rabbit needs the SLP to listen.", []),
                              (" Nothing needs the SLP to listen.", ["red"])):
            with self.subTest(extra), self.assertRaises(ValueError):
                check_reply(SESSION_AT_90 + extra, SESSION, 90, listen)
        with self.assertRaises(ValueError):
            check_reply(CLEAN_AT_90 + " Nobody needs the SLP to listen.", CLEAN, 90, ["carrot"])

    def test_check_accepts_the_listen_line_as_qwen_writes_it(self):
        # #50: with listen words in the facts, the one true listen sentence Qwen2.5-0.5B wrote (2 of 41 notes, Nov 14)
        # copies the facts line.
        results = [_try("rabbit", "gliding", "w"), _try("ring"), _try("door")]
        reply = ("The child tried 3 words with the r sound. Rabbit had gliding (heard w), so normal for age. "
                 "SLP please listen: ring, door.")
        self.assertEqual(check_reply(reply, results, 59, ["ring", "door"]), reply)
        self.assertEqual(check_reply(reply.replace("ring, door", "door"), results, 59, ["ring", "door"]),
                         reply.replace("ring, door", "door"))
        for line, listen in (("SLP please listen: ring, door.", ["ring"]), ("SLP please listen: ring, rabbit.", ["ring"]),
                             ("SLP please listen: banana.", ["ring"]), ("SLP please listen: nothing.", ["ring"]),
                             ("SLP please listen: ring, door, all.", ["ring", "door"]),
                             ("SLP please listen: ring, so flagged for age.", ["ring"]),
                             ("SLP please listen: ring had gliding.", ["ring"]),
                             ("SLP please listen: ring, ring.", ["ring", "door"]),
                             ("SLP please listen: ring, door, ring.", ["ring", "door"])):
            with self.subTest(line), self.assertRaises(ValueError):
                check_reply(reply.replace("SLP please listen: ring, door.", line), results, 59, listen)

    def test_note_is_the_checked_reply(self):
        model = FakeModel("  " + S1_AT_96 + "\n")
        self.assertEqual(note(S1, 96, model), S1_AT_96)
        self.assertEqual(model.prompts, [build_prompt(S1, 96)])

    def test_note_rejects_a_wrong_reply(self):
        with self.assertRaises(ValueError):
            note(S1, 96, FakeModel("Pass."))

    def test_empty_session_raises_before_the_model(self):
        model = FakeModel("x")
        with self.assertRaises(ValueError):
            note([], 90, model)
        self.assertEqual(model.prompts, [])


if __name__ == "__main__":
    unittest.main()
