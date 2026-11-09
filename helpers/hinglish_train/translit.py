"""Devanagari to Roman Hinglish on this computer, by rule: no Claude calls (a usage limit stopped them halfway).
Letters map the way Indians type Hindi in chat; the "a" a consonant carries is dropped where Hindi doesn't say it
(word-final, and between a vowel and a following consonant-vowel: करते -> karte); the commonest words use their
usual chat spellings. Latin words pass through. Checked against Claude's conversions in roman.jsonl (romanize.py)."""
import re
from difflib import SequenceMatcher

CONSONANTS = {"क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "n", "च": "ch", "छ": "chh", "ज": "j", "झ": "jh", "ञ": "n",
              "ट": "t", "ठ": "th", "ड": "d", "ढ": "dh", "ण": "n", "त": "t", "थ": "th", "द": "d", "ध": "dh", "न": "n",
              "प": "p", "फ": "ph", "ब": "b", "भ": "bh", "म": "m", "य": "y", "र": "r", "ल": "l", "व": "v", "श": "sh",
              "ष": "sh", "स": "s", "ह": "h", "ळ": "l"}
NUKTA = {"क": "q", "ख": "kh", "ग": "g", "ज": "z", "ड": "d", "ढ": "dh", "फ": "f", "य": "y"}
VOWELS = {"अ": "a", "आ": "aa", "इ": "i", "ई": "ee", "उ": "u", "ऊ": "oo", "ऋ": "ri", "ए": "e", "ऐ": "ai", "ओ": "o",
          "औ": "au", "ऑ": "o", "ऍ": "e"}
SIGNS = {"ा": "aa", "ि": "i", "ी": "ee", "ु": "u", "ू": "oo", "ृ": "ri", "े": "e", "ै": "ai", "ो": "o", "ौ": "au",
         "ॉ": "o", "ॅ": "e"}
DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
COMMON = {"है": "hai", "हैं": "hain", "में": "mein", "नहीं": "nahi", "करें": "karein", "के": "ke", "की": "ki",
          "को": "ko", "का": "ka", "से": "se", "यह": "yeh", "वह": "woh", "ये": "ye", "वो": "wo", "और": "aur",
          "क्या": "kya", "आप": "aap", "हम": "hum", "तो": "to", "भी": "bhi", "लिए": "liye", "पर": "par", "एक": "ek",
          "हो": "ho", "कि": "ki", "जो": "jo", "कर": "kar", "अब": "ab", "जब": "jab", "तब": "tab", "सब": "sab",
          "यहाँ": "yahan", "यहां": "yahan", "वहाँ": "wahan", "वहां": "wahan", "मैं": "main", "हूँ": "hoon",
          "हूं": "hoon", "था": "tha", "थी": "thi", "थे": "the", "गया": "gaya", "रहा": "raha", "रही": "rahi",
          "रहे": "rahe", "इस": "is", "उस": "us", "इसे": "ise", "उसे": "use", "कैसे": "kaise", "ऐसे": "aise",
          "अपने": "apne", "अपना": "apna", "सकते": "sakte", "करते": "karte", "करने": "karne", "होता": "hota",
          "होती": "hoti", "होते": "hote", "जाता": "jaata", "जाती": "jaati", "जाते": "jaate", "दिया": "diya",
          "किया": "kiya", "लिया": "liya", "चाहिए": "chahiye", "हमें": "hamein", "उन्हें": "unhein", "करता": "karta",
          "करती": "karti", "हमने": "hamne", "बंद": "band", "तुलना": "tulna", "करना": "karna", "करके": "karke",
          # Hindi words that sound like a tutorial's English ones (bindu / bond, saral / serial): never swapped
          "बिंदु": "bindu", "श्रुति": "shruti", "शुरुआत": "shuruaat", "वृत्त": "vritt", "अर्थ": "arth", "सरल": "saral"}


def word(w):
    """One Devanagari word in Roman letters."""
    if w in COMMON:
        return COMMON[w]
    units = []  # [consonant or "", vowel, inherent?] per syllable
    i = 0
    while i < len(w):
        ch = w[i]
        if ch in CONSONANTS:
            sound = CONSONANTS[ch]
            if i + 1 < len(w) and w[i + 1] == "़":
                sound, i = NUKTA.get(ch, sound), i + 1
            units.append([sound, "a", True])
        elif ch in SIGNS and units:
            units[-1][1], units[-1][2] = SIGNS[ch], False
        elif ch == "्" and units:
            units[-1][1], units[-1][2] = "", False
        elif ch in VOWELS:
            units.append(["", VOWELS[ch], False])
        elif ch in "ंँ":
            if units:
                units[-1][1] += "n"
                units[-1][2] = False
        elif ch == "ः":
            if units:
                units[-1][1] += "h"
        elif ch == "़":
            pass
        else:
            units.append([ch.translate(DIGITS), "", False])
        i += 1
    # the "a" Hindi doesn't say: at the end of a word of 2+ syllables, and in a vowel, consonant-a, consonant-vowel run
    if len(units) > 1 and units[-1][2]:
        units[-1][1] = ""
    for j in range(len(units) - 2, 0, -1):
        if units[j][2] and units[j - 1][1] and units[j + 1][0] and units[j + 1][1]:
            units[j][1] = ""
            units[j - 1][2] = False  # never two dropped in a row
    out = "".join(c + v for c, v, _ in units)
    if len(units) > 1:  # chat spelling ends a word short: karta, saara, hui (not kartaa, saaraa, huee)
        out = re.sub(r"aa$", "a", re.sub(r"ee$", "i", out))
    return chat(out)


def chat(w):
    """The spellings people type, each measured against Claude's conversions (closer to them, or left out): hi, di, ya
    (not hee, dee, yaa), kuch (kuchh), swagat, dwara (svaagat, dvaara), jaayein (jaaen), hamari (hamaari)."""
    w = re.sub(r"^([^aeiou]{1,2})aa$", r"\1a", re.sub(r"^([^aeiou]{1,2})ee$", r"\1i", w))
    w = re.sub(r"chh$", "ch", w.replace("chchh", "chh"))
    w = re.sub(r"(?<=[sdtkjgbh])v", "w", w)
    w = re.sub(r"aaen$", "aayein", re.sub(r"aae$", "aaye", w))
    if len(re.findall(r"[aeiou]+", w)) >= 3:  # a long vowel past the first syllable, before a final one, goes short
        w = re.sub(r"(?<=[^aeiou])aa(?=[^aeiou](?:i|ee|e|a)\b)", "a", w)
    return w


def skeleton(w):
    """How a word sounds, roughly: its consonants ("slaid" and "slide" -> "sld", "phont" and "font" -> "fnt")."""
    w = re.sub(r"c(?=[eiy])", "s", w.lower())
    w = w.replace("ph", "f").replace("ck", "k").replace("c", "k").replace("w", "v").replace("q", "k").replace("x", "ks")
    return re.sub(r"(.)\1+", r"\1", re.sub(r"[aeiouy]", "", w))  # h stays: aspiration tells kholen from colon


def english(texts, least=5):
    """{skeleton: word}: the English words a corpus already writes in Latin letters (at least `least` times), to put
    back English words its transcripts spell in Devanagari (स्लाइड -> slide). Ambiguous skeletons are left out."""
    counts = {}
    for text in texts:
        for w in re.findall(r"\b[A-Za-z][a-z]{2,}\b", text):
            counts[w.lower()] = counts.get(w.lower(), 0) + 1
    by = {}
    for w, n in counts.items():
        if n >= least and len(skeleton(w)) >= 3:
            by.setdefault(skeleton(w), []).append((n, w))
    return {k: max(v)[1] for k, v in by.items() if len(v) == 1 or max(v)[0] >= 3 * sorted(v)[-2][0]}


def roman(text, vocabulary=None):
    """A transcript: Devanagari words converted (to the corpus's English word when they are one, with `vocabulary`
    from english()), Latin words, numbers and punctuation kept."""
    def one(m):
        dev = m.group(0)
        out = word(dev)
        swap = vocabulary and dev not in COMMON and vocabulary.get(skeleton(out))
        # the same consonants are not enough ("karta" / "create"): the spelling must look like the word too
        return swap if swap and SequenceMatcher(None, out, swap).ratio() >= 0.6 else out
    return re.sub(r"[ऀ-ॿ]+", one, text).replace("।", ".")


if __name__ == "__main__":  # how close the rules come to Claude's conversions
    import json
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from common import OUT
    from stt_bench import error_rates
    claude = {r["id"]: r["text"] for r in map(json.loads, (OUT / "roman.jsonl").open(encoding="utf-8")) if r.get("lang", "hi") == "hi"}
    pairs = [(r["text"], claude[r["id"]]) for r in map(json.loads, (OUT / "manifest.jsonl").open(encoding="utf-8"))
             if r["id"] in claude][:2000]
    w = c = 0.0
    for dev, want in pairs:
        a, b = error_rates(roman(dev), want)
        w, c = w + a, c + b
    print(f"{len(pairs)} lines against Claude: words differ {w / len(pairs):.1%}, letters {c / len(pairs):.1%}")
    for dev, want in pairs[:8]:
        print(f"  {roman(dev)}\n  {want}\n")
