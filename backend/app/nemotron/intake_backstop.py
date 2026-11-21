"""Deterministic backstops for intake: dollar amounts, carrier names, ride need, identifier detection and time-phrase resolution. Pure functions over the utterance; nothing here touches the network."""

from __future__ import annotations

import re
from datetime import datetime, timedelta

_WORD_NUMBERS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
    "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
    "seventy": 70, "eighty": 80, "ninety": 90,
}

# Carrier spellings a speaker uses -> the carrier name the clinic knows. Longest match wins.
CARRIERS: dict[str, str] = {
    "delta dental": "Delta Dental",
    "delta": "Delta Dental",
    "medicare": "Medicare",
    "medicaid": "Medicaid",
    "aetna": "Aetna",
    "blue cross blue shield": "Blue Cross Blue Shield",
    "blue cross": "Blue Cross Blue Shield",
    "bcbs": "Blue Cross Blue Shield",
    "humana": "Humana",
    "unitedhealthcare": "UnitedHealthcare",
    "united healthcare": "UnitedHealthcare",
    "united health": "UnitedHealthcare",
    "cigna": "Cigna",
    "vsp": "VSP",
    "kaiser": "Kaiser Permanente",
}

_BUDGET_CUE = r"(?:under|below|less than|no more than|not more than|max(?:imum)?|up to|around|about|tops|budget|spend|keep it|cap)"
_DOLLAR_NUMBER = re.compile(r"\$\s?(\d{1,3}(?:,\d{3})*|\d+)(?:\.\d+)?")
_NUMBER_DOLLARS = re.compile(r"\b(\d{2,4})\s*(?:dollars|bucks)\b", re.IGNORECASE)
_TRAILING_TOPS = re.compile(r"\b(\d{2,4}|[a-z]+(?:[ -][a-z]+){0,4})\s+tops\b", re.IGNORECASE)
_BUDGET_CUE_RE = re.compile(r"\b" + _BUDGET_CUE + r"\b", re.IGNORECASE)
_FILLERS = {"a", "an", "the", "more", "than", "about", "around", "of", "to", "roughly", "like", "just", "is", "it", "at", "most"}

_RIDE_YES = re.compile(
    r"need (?:a |someone to )?(?:ride|drive me|lift)|needs? a ride|don'?t have a car|no car\b|can'?t drive|cannot drive|"
    r"shouldn'?t drive|not drive|ride there|can'?t take the bus|someone to drive|drive me|\ba ride\b",
    re.IGNORECASE,
)
_RIDE_NO = re.compile(r"drive myself|get there on my own|can drive\b|my own car|i'?ll drive", re.IGNORECASE)

_MEMBER_ID = re.compile(r"\b(?:[A-Z]{2,6}-)?(?:\d{3,}-)+\d{2,}\b|\b[A-Z]{2,6}\d{6,}\b|\bDEMO-[\w-]+")
_PHONE = re.compile(r"(?:\+?1[ -.]?)?\(?\d{3}\)?[ -.]\d{3}[ -.]\d{4}\b")
_DOB = re.compile(
    r"\b(?:born|date of birth|dob|birthday)\b|\b\d{1,2}/\d{1,2}/\d{2,4}\b|"
    r"\b(?:january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2},?\s+(?:19|20)\d{2}\b",
    re.IGNORECASE,
)
_ADDRESS = re.compile(
    r"\b\d{1,6}\s+[A-Z][\w.]*(?:\s+[A-Z][\w.]*){0,3}\s+(?:street|st|avenue|ave|road|rd|lane|ln|drive|dr|boulevard|blvd|way|court|ct|place|pl)\b"
    r"|\blive (?:at|on)\b",
    re.IGNORECASE,
)

DROPPABLE_ORDER = ("symptoms", "medications", "member_id", "date_of_birth", "address", "contact_phone", "patient_name", "mobility_details").index

TIME_PHRASES = ("this week", "next week", "tomorrow", "this month", "next month", "within two weeks", "any")
_TIME_CUES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\btomorrow\b", re.IGNORECASE), "tomorrow"),
    (re.compile(r"\bthis week\b", re.IGNORECASE), "this week"),
    (re.compile(r"\bnext week\b", re.IGNORECASE), "next week"),
    (re.compile(r"\bthis month\b", re.IGNORECASE), "this month"),
    (re.compile(r"\bnext month\b", re.IGNORECASE), "next month"),
    (re.compile(r"\b(?:within|in) the next (?:two|2) weeks\b|\b(?:within|in) (?:two|2) weeks\b|\bnext two weeks\b", re.IGNORECASE), "within two weeks"),
)


def words_to_number(text: str) -> int | None:
    """"two hundred" -> 200, "one fifty" -> 150, "a hundred and twenty-five" -> 125, "forty" -> 40."""
    tokens = [t for t in re.split(r"[\s-]+", text.lower().strip()) if t and t not in {"and", "a", "an"}]
    if not tokens:
        return None
    total = 0
    current = 0
    for tok in tokens:
        if tok in _WORD_NUMBERS:
            current += _WORD_NUMBERS[tok]
        elif tok == "hundred":
            current = (current or 1) * 100
        elif tok == "thousand":
            current = (current or 1) * 1000
        elif tok.isdigit():
            current += int(tok)
        else:
            return None
    total += current
    if total <= 0:
        return None
    # "one fifty" is 150, not 51: a small leading number followed by a tens word.
    if len(tokens) == 2 and tokens[0] in _WORD_NUMBERS and _WORD_NUMBERS[tokens[0]] < 10 and tokens[1] in _WORD_NUMBERS and _WORD_NUMBERS[tokens[1]] >= 20:
        return _WORD_NUMBERS[tokens[0]] * 100 + _WORD_NUMBERS[tokens[1]]
    return total


def extract_budget(utterance: str) -> int | None:
    """Dollar cap stated in the utterance, or None. Digits first, then spelled-out amounts after a budget cue."""
    m = _DOLLAR_NUMBER.search(utterance)
    if m:
        return int(m.group(1).replace(",", ""))
    m = _NUMBER_DOLLARS.search(utterance)
    if m:
        return int(m.group(1))
    m = _TRAILING_TOPS.search(utterance)
    if m:
        value = int(m.group(1)) if m.group(1).isdigit() else words_to_number(m.group(1))
        if value:
            return value
    for cue in _BUDGET_CUE_RE.finditer(utterance):
        tokens = re.findall(r"[a-z]+(?:-[a-z]+)?", utterance[cue.end():].lower())[:8]
        while tokens and tokens[0] in _FILLERS:
            tokens.pop(0)
        for n in range(min(len(tokens), 5), 0, -1):
            value = words_to_number(" ".join(tokens[:n]))
            if value and value >= 10:
                return value
    return None


def extract_carrier(utterance: str) -> str | None:
    low = utterance.lower()
    if re.search(r"\bno insurance\b|\bnot insured\b|\bpay cash\b", low) and not any(k in low for k in CARRIERS):
        return None
    for key in sorted(CARRIERS, key=len, reverse=True):
        if re.search(r"\b" + re.escape(key) + r"\b", low):
            return CARRIERS[key]
    return None


def extract_needs_ride(utterance: str) -> bool | None:
    """True, False, or None when the utterance says nothing about getting there."""
    if _RIDE_NO.search(utterance):
        return False
    if _RIDE_YES.search(utterance):
        return True
    return None


def detect_identifiers(utterance: str) -> list[str]:
    """Kinds of identifier present in the text, by pattern: member_id, contact_phone, date_of_birth, address."""
    found: list[str] = []
    stripped = _PHONE.sub(" ", utterance)
    if _MEMBER_ID.search(stripped):
        found.append("member_id")
    if _PHONE.search(utterance):
        found.append("contact_phone")
    if _DOB.search(utterance):
        found.append("date_of_birth")
    if _ADDRESS.search(utterance):
        found.append("address")
    return found


def extract_time_phrase(utterance: str) -> str | None:
    for pattern, phrase in _TIME_CUES:
        if pattern.search(utterance):
            return phrase
    return None


def resolve_time_range(phrase: str, now: datetime) -> tuple[str, str]:
    """Phrase -> (start, end) ISO date-times in now's timezone. Unknown phrases resolve like "within two weeks"."""
    phrase = (phrase or "").strip().lower()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if phrase == "tomorrow":
        start, end_day = today + timedelta(days=1), today + timedelta(days=1)
    elif phrase == "this week":
        start, end_day = today, today + timedelta(days=6 - today.weekday())
    elif phrase == "next week":
        start = today + timedelta(days=7 - today.weekday())
        end_day = start + timedelta(days=6)
    elif phrase == "this month":
        start = today
        end_day = (today.replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    elif phrase == "next month":
        start = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
        end_day = (start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    elif phrase == "any":
        start, end_day = today, today + timedelta(days=29)
    else:
        start, end_day = today, today + timedelta(days=13)
    end = end_day.replace(hour=23, minute=59, second=59)
    return start.isoformat(), end.isoformat()


def identifier_values(utterance: str) -> list[str]:
    """The literal identifier strings in the text (member IDs, phone numbers, dates, street addresses), for the leak check."""
    values: list[str] = []
    for pattern in (_PHONE, _MEMBER_ID, _ADDRESS):
        values.extend(m.group(0) for m in pattern.finditer(utterance) if len(m.group(0)) >= 6)
    for m in _DOB.finditer(utterance):
        if re.search(r"\d", m.group(0)):
            values.append(m.group(0))
    return [v for v in values if not re.fullmatch(r"live (?:at|on)", v, re.IGNORECASE)]


# Words that name a symptom, condition, body part, mobility aid or medication. A fail-closed check on what leaves
# the device, not the redactor itself: Nano drops these; this catches the case where it did not.
SENSITIVE_WORDS: frozenset[str] = frozenset(
    {
        "pain", "ache", "toothache", "headache", "hurt", "hurts", "hurting", "sore", "swelling", "swollen", "bleeding",
        "fever", "cough", "dizzy", "dizziness", "nausea", "infection", "infected", "cavity", "broken", "fracture",
        "spasm", "spasms", "spasming", "mole", "rash", "diabetes", "diabetic", "cancer", "tumor", "pacemaker", "stroke",
        "dementia", "alzheimer", "arthritis", "depression", "anxiety", "pregnant", "hiv", "chest", "knee", "hip",
        "shoulder", "stomach", "throat", "ear", "lump", "wound", "injury", "injured", "symptom", "symptoms", "diagnosed",
        "walker", "wheelchair", "cane", "crutches", "fall", "fell", "fallen",
        "insulin", "aspirin", "ibuprofen", "tylenol", "advil", "vicodin", "warfarin", "metformin", "lisinopril",
        "prednisone", "xanax", "oxycodone", "morphine", "medication", "medications", "pills", "prescription",
    }
)
_DRUG_SUFFIX = re.compile(r"\b\w{3,}(?:mycin|cillin|pril|statin|formin|olol|prazole|sartan|azepam|oxetine|dipine|tidine|vir|mab)\b", re.IGNORECASE)
_CARE_TYPE_CUT = re.compile(r"\s+(?:for|because|due to|since|with|as|after|about|regarding)\s+|[,;:(]|\s[-\u2013\u2014]\s", re.IGNORECASE)


def normalise_care_type(text: str) -> str:
    """Keep the appointment kind and nothing after it: "dental cleaning for a toothache" -> "dental cleaning".

    Lowercase, cut at the first connective or punctuation, letters and hyphens only, at most four words.
    Returns "" when nothing usable is left.
    """
    head = _CARE_TYPE_CUT.split(text.strip().lower(), maxsplit=1)[0]
    words = [w for w in re.findall(r"[a-z]+(?:-[a-z]+)?", head) if w not in {"a", "an", "the", "my", "me"}]
    return " ".join(words[:4])


def unsafe_terms(text: str, extra_values: list[str] = ()) -> list[str]:
    """Sensitive words, drug-like words and any of extra_values (the owner's own identifiers) present in text."""
    low = text.lower()
    found = [w for w in re.findall(r"[a-z]+(?:-[a-z]+)?", low) if w in SENSITIVE_WORDS]
    found += [m.group(0) for m in _DRUG_SUFFIX.finditer(low)]
    found += [v for v in extra_values if v and len(v) >= 3 and v.lower() in low]
    return found


# The appointment words a care_type may be made of. Anything else (a name, a symptom, an unknown procedure) fails closed:
# the request is refused and the speaker is asked again, rather than an unknown word leaving the device.
CARE_TYPE_VOCAB: frozenset[str] = frozenset(
    {
        "dental", "dentist", "teeth", "tooth", "cleaning", "filling", "crown", "root", "canal", "extraction", "denture",
        "dentures", "orthodontic", "orthodontist", "braces", "whitening", "gum", "periodontal", "oral", "hygiene",
        "eye", "eyes", "vision", "optometry", "optometrist", "ophthalmology", "ophthalmologist", "glasses", "contacts",
        "hearing", "audiology", "audiologist", "aid", "aids", "fitting", "ent",
        "flu", "shot", "shots", "vaccine", "vaccination", "booster", "covid", "shingles", "pneumonia", "tetanus", "immunization",
        "physical", "annual", "wellness", "checkup", "check-up", "check", "up", "exam", "examination", "visit", "consult",
        "consultation", "appointment", "primary", "care", "doctor", "gp", "nurse", "follow-up", "followup", "follow",
        "blood", "test", "tests", "lab", "labs", "work", "panel", "urine", "cholesterol", "glucose", "a1c",
        "x-ray", "xray", "mri", "ct", "scan", "ultrasound", "mammogram", "colonoscopy", "screening", "bone", "density", "dexa",
        "dermatology", "dermatologist", "skin", "podiatry", "podiatrist", "foot", "feet", "nail",
        "therapy", "physiotherapy", "physiotherapist", "rehab", "rehabilitation", "occupational", "speech", "massage",
        "chiropractic", "chiropractor", "adjustment", "acupuncture",
        "cardiology", "cardiologist", "heart", "echo", "echocardiogram", "ekg", "ecg", "stress",
        "neurology", "neurologist", "orthopedic", "orthopedics", "orthopedist", "urology", "urologist", "gynecology",
        "gynecologist", "obgyn", "endocrinology", "endocrinologist", "gastroenterology", "gastroenterologist", "rheumatology",
        "rheumatologist", "pulmonology", "pulmonologist", "oncology", "oncologist", "nephrology", "nephrologist", "allergy",
        "allergist", "psychiatry", "psychiatrist", "counseling", "counselling", "psychologist", "psychotherapy",
        "pharmacy", "refill", "medication", "review", "injection", "infusion", "dialysis", "sleep", "study",
        "pre-op", "post-op", "surgical", "surgery", "specialist", "referral", "second", "opinion", "telehealth", "video",
        "home", "health", "aide", "memory", "clinic", "geriatric", "geriatrics", "fall", "risk", "assessment", "diabetes", "diabetic",
    }
)
_PLACE = re.compile(r"^[A-Z][A-Za-z.'\- ]{1,40}, [A-Z]{2}$")


def unsupported_care_terms(care_type: str) -> list[str]:
    """Words in a normalised care_type that are not appointment vocabulary."""
    return [w for w in care_type.split() if w not in CARE_TYPE_VOCAB]


def looks_like_place(area: str) -> bool:
    """"Evanston, IL" or "Oak Park, IL": a place name with a state code, at most four words."""
    return bool(_PLACE.match(area)) and len(area.split()) <= 4
