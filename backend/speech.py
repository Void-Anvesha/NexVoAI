"""Rewrite times and dates into words right before text-to-speech.

The LLM writes "11:00" or "2026-11-26" (the formats the tools use), and the
TTS voice reads those literally: "eleven zero zero". This transform runs only
on the text sent to TTS; the on-screen transcript keeps the original text.
"""
import re
from datetime import date

ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
        "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
        "seventeen", "eighteen", "nineteen"]
TENS = {2: "twenty", 3: "thirty", 4: "forty", 5: "fifty"}
ORDINALS = {1: "first", 2: "second", 3: "third", 5: "fifth", 8: "eighth", 9: "ninth", 12: "twelfth"}


def number_words(n: int) -> str:
    if n < 20:
        return ONES[n]
    tens, ones = divmod(n, 10)
    return TENS[tens] + (f"-{ONES[ones]}" if ones else "")


def ordinal_words(n: int) -> str:
    """1 -> first, 22 -> twenty-second, 30 -> thirtieth."""
    tens, ones = divmod(n, 10)
    if n < 20:
        return ORDINALS.get(n, ONES[n] + "th")
    if ones == 0:
        return TENS[tens][:-1] + "ieth"
    return f"{TENS[tens]}-{ORDINALS.get(ones, ONES[ones] + 'th')}"


# 11:00, 9:30, 14:30, optionally followed by AM/PM (or a.m./p.m.)
# (a trailing "." is only eaten for the dotted "a.m."/"p.m." form, so the full
# stop after "11:00 AM." survives)
TIME_RE = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)(?:\s*([AaPp])(\.)?\s*[Mm](?(4)\.))?(?![\w:])")
DATE_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
# Phone numbers: 7+ digits, optionally grouped with spaces/dashes/dots and a
# leading +. Not preceded by a letter or dash, so ids like CL-261125-0022 stay.
PHONE_RE = re.compile(r"(?<![\w-])\+?\d(?:[\s.-]?\d){6,}(?![\w-])")


def _time(m: re.Match) -> str:
    hour, minute, meridiem = int(m.group(1)), int(m.group(2)), m.group(3)
    if meridiem:
        suffix = "AM" if meridiem.lower() == "a" else "PM"
    else:
        suffix = "AM" if hour < 12 else "PM"
    hour12 = hour % 12 or 12
    if minute == 0:
        return f"{number_words(hour12)} {suffix}"
    mins = f"oh {number_words(minute)}" if minute < 10 else number_words(minute)
    return f"{number_words(hour12)} {mins} {suffix}"


def _date(m: re.Match) -> str:
    try:
        d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return m.group(0)
    return f"{d:%A}, {d:%B} {ordinal_words(d.day)}"


def _phone(m: re.Match) -> str:
    """98765 43210 / 987-654-3210 -> "9 8 7 6 5, 4 3 2 1 0": read digit by
    digit, pausing (comma) where the number's groups were."""
    raw = m.group(0)
    groups = [g for g in re.split(r"[\s.-]+", raw.lstrip("+")) if g]
    if len(groups) == 1 and len(groups[0]) > 7:  # ungrouped: pause after 5 digits
        groups = [groups[0][:5], groups[0][5:]]
    spoken = ", ".join(" ".join(g) for g in groups)
    return ("plus " if raw.startswith("+") else "") + spoken


def to_spoken(text: str) -> str:
    text = DATE_RE.sub(_date, text)
    text = PHONE_RE.sub(_phone, text)
    return TIME_RE.sub(_time, text)


async def spoken_times_and_dates(text: str, text_type) -> str:
    """Pipecat TextTransform: (text, text_type) -> text."""
    return to_spoken(text)
