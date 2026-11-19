"""Hindi copy: site "hindi_copy": true keeps the English letter and also asks its writer for a faithful Hindi
translation for the local office. Code then checks that the copy holds exactly the English letter's numbers (Devanagari
digits read as digits, numbers in words of either language refused), so a translation can add or change none."""
import collections
import json
import re
import unicodedata

PROMPT = """Translate the formal letter below from English into Hindi (Devanagari script) for the local office of the
road authority. Translate it faithfully, sentence by sentence: add nothing, leave nothing out, and add no fact, name,
place, date or number. Keep every number in digits exactly as the English letter writes it (0.4 stays 0.4, 1,200
stays 1,200) with its unit (km/h, s, %); never write a number in words.

Reply with JSON only: {{"letter_hi": "<the Hindi letter>"}}

ENGLISH LETTER:
{letter}"""
SCHEMA = {"type": "object", "properties": {"letter_hi": {"type": "string"}}, "required": ["letter_hi"],
          "additionalProperties": False}  # for an open-weights writer
TRIES = 3  # the first translation and up to 2 more while its numbers differ from the English letter's
DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
# numbers in Hindi words, which code cannot check: एक is left out (it is also "a"), as English leaves out "one"
WORDS = unicodedata.normalize("NFC", "दो|तीन|चार|पाँच|पांच|छह|छः|सात|आठ|नौ|दस|ग्यारह|बारह|तेरह|चौदह|पंद्रह|पन्द्रह|सोलह|"
                              "सत्रह|अठारह|उन्नीस|बीस|तीस|चालीस|पचास|साठ|सत्तर|अस्सी|नब्बे|सौ|सैकड़ों|सैकड़ा|हज़ार|"
                              "हजार|हज़ारों|हजारों|लाख|लाखों|करोड़|करोड़ों|दर्जन|दर्जनों")
# a Devanagari letter or vowel sign on either side makes it part of a longer word: विचार holds चार, दोनों holds दो
NUMBER_WORD = re.compile(rf"(?<![\u0900-\u097f])(?:{WORDS})(?![\u0900-\u097f])")
UNREADABLE = (ValueError, KeyError, TypeError, AttributeError)  # a reply of the wrong shape; a server error is raised


def numbers(text, number):
    """The values of the numbers `number` (pack.NUMBER) finds in `text`, Devanagari digits read as digits, counted."""
    return collections.Counter(float(n.replace(",", "")) for n in number.findall(text.translate(DIGITS)))


def mismatch(english, hindi, number, number_word):
    """Why `hindi` does not hold exactly `english`'s numbers ("" when it does): a number missing or added, or a number
    in words (pack.NUMBER_WORD's English ones, or Hindi ones)."""
    want, got = numbers(english, number), numbers(hindi, number)
    show = lambda counter: ", ".join(f"{v:g}" for v in sorted(counter.elements()))
    words = [m[0] for p in (number_word, NUMBER_WORD) for m in p.finditer(unicodedata.normalize("NFC", hindi))]
    return "; ".join(([f"missing {show(want - got)}"] if want - got else [])
                     + ([f"not in the English letter: {show(got - want)}"] if got - want else [])
                     + ([f"numbers in words: {', '.join(dict.fromkeys(words))}"] if words else []))


def translate(letter, ask, number, number_word):
    """(the Hindi copy, "") or ("", why there is none). `ask(prompt)` is the English letter's writer; a reply whose
    numbers differ (mismatch) or that cannot be read goes back with the reason, at most TRIES replies in all. A
    server error (OSError, http.client.HTTPException) is raised: the next run asks again."""
    note, why = "", ""
    for _ in range(TRIES):
        try:
            reply = json.loads(re.search(r"\{.*\}", ask(PROMPT.format(letter=letter) + note), re.S)[0], strict=False)
            text = reply["letter_hi"].strip()
        except UNREADABLE as err:
            why = f"the reply could not be read: {str(err)[:200]}"
            note = "\n\nYour previous reply could not be read. Reply with the JSON object only."
            continue
        why = mismatch(letter, text, number, number_word) if text else "the reply was empty"
        if not why:
            return text, ""
        note = (f"\n\nYour previous translation did not keep the English letter's numbers ({why}). Keep every number "
                "exactly as the English letter writes it, in digits, and add none.")
    return "", f"no translation kept the English letter's numbers in {TRIES} tries ({why})"
