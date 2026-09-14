"""
apps/ai/phi_scrubber.py — de-identification of clinical text before it leaves the
perimeter (Onda 3 / 3.1).

Two layers, deliberately different in what they can guarantee:

1. Directed substitution (``scrub_patient_identifiers``): every identifier we
   already hold for the encounter's ``Patient`` (full_name, social_name,
   mother/father name, cpf, cns, identity_document/RG, phone, email,
   birth_date — the same fields already decrypted for this request) is
   replaced by a stable token. This is the trustworthy path: it is matching
   against a KNOWN value, not guessing a pattern, so it reliably covers the
   dominant case — the patient the encounter is actually about.

2. Generic regex sweep (``scrub_generic``): CPF, CNS, phone, e-mail and
   date-shaped substrings are scrubbed WITHOUT needing a ``Patient`` at all.
   This catches structured identifiers belonging to someone who is NOT the
   encounter's patient — a spouse's CPF dictated into the transcription, a
   phone number the patient recites for a relative — because those follow
   strict enough formats for regex to match.

Tokens are STABLE: the same input value always produces the same
``[KIND_xxxxxxxx]`` token (an 8-hex digest of the normalized value), so a name
or CPF mentioned five times in one transcription collapses to five identical
tokens — this keeps the text coherent for the LLM (it can still tell "the
patient" apart from "the referring doctor") without leaking the actual value.

WHAT THIS DOES **NOT** CATCH — read before trusting it:

  - Free-form names that are not on file for this patient (not the patient's
    own name/social name/parents). "Encaminhei para o Dr. Fulano de Tal" or a
    transcription naming a third party (another patient, a witness, a
    colleague) passes through untouched. There is no reliable regex for
    "this token sequence is a person's name" in Portuguese free text without
    an NER model, and this module does not ship one.
  - Addresses, employer, school, or any narrative detail that identifies
    someone indirectly ("mora ao lado da igreja de São Judas").
  - Misspelled/abbreviated variants of the patient's own name that don't
    literally appear as a substring of ``full_name``/``social_name`` (e.g. a
    transcription that only ever says "dona Bete" for a patient registered
    as "Elizabete Ferreira").
  - Numbers that happen to look like a CPF/CNS/phone but are not one, and
    conversely CPF/CNS typed with unexpected separators may slip past the
    regex (e.g. spelled out digit-by-digit by dictation software).

This is mitigation for the dominant case, not anonymization. Do not represent
scrubbed text as PHI-free to compliance/legal — it is "the known identifiers
for this record are gone", not "no PHI could possibly remain".

Audio is entirely out of scope for this module — see
``apps/emr/services/whisper.py`` for why voice cannot be de-identified by
rewriting text.
"""

from __future__ import annotations

import hashlib
import re

_CPF_RE = re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")
_CNS_RE = re.compile(r"\b\d{3}\s?\d{4}\s?\d{4}\s?\d{4}\b")
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_PHONE_RE = re.compile(r"\b(?:\+?55\s?)?\(?\d{2}\)?\s?9?\d{4}-?\d{4}\b")
_DATE_RE = re.compile(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b")

# Order matters: match the more specific/longer patterns before the looser
# ones so e.g. an e-mail's digits are never partially eaten by the phone regex.
_GENERIC_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("EMAIL", _EMAIL_RE),
    ("CPF", _CPF_RE),
    ("CNS", _CNS_RE),
    ("TEL", _PHONE_RE),
    ("DATA", _DATE_RE),
]

# Minimum length for an individual name token (first name, surname) to be
# scrubbed on its own — below this, common short Portuguese words would be
# over-redacted too often to be worth it.
_MIN_NAME_TOKEN_LEN = 4


def _token(kind: str, value: str) -> str:
    """Stable token for `value`: same input -> same token, always."""
    digest = hashlib.sha256(value.strip().lower().encode("utf-8")).hexdigest()[:8].upper()
    return f"[{kind}_{digest}]"


def _replace_literal(text: str, value: str, kind: str) -> str:
    value = (value or "").strip()
    if not value:
        return text
    token = _token(kind, value)
    return re.sub(re.escape(value), token, text, flags=re.IGNORECASE)


def scrub_patient_identifiers(text: str, patient: object | None) -> str:
    """
    Directed substitution using known ``Patient`` fields.

    `patient` is duck-typed on purpose (no import of ``apps.emr.models`` here)
    — any object exposing the attributes below works, including a plain
    namespace in tests. Missing/blank attributes are silently skipped.
    """
    if not text or patient is None:
        return text

    out = text
    for attr, kind in (
        ("full_name", "NOME"),
        ("social_name", "NOME"),
        ("mother_name", "NOME"),
        ("father_name", "NOME"),
        ("cpf", "CPF"),
        ("cns", "CNS"),
        ("identity_document", "RG"),
        ("phone", "TEL"),
        ("email", "EMAIL"),
    ):
        value = getattr(patient, attr, "") or ""
        value = str(value).strip()
        if not value:
            continue
        out = _replace_literal(out, value, kind)
        if attr in ("full_name", "social_name"):
            # Also scrub individual name parts (e.g. just the surname used
            # informally: "dona Maria", "Sr. Ferreira") — best-effort, see
            # module docstring on over-redaction trade-off.
            for part in value.split():
                if len(part) >= _MIN_NAME_TOKEN_LEN:
                    out = _replace_literal(out, part, kind)

    birth_date = getattr(patient, "birth_date", None)
    if birth_date is not None:
        token = _token("NASC", birth_date.isoformat())
        for variant in (
            birth_date.strftime("%d/%m/%Y"),
            birth_date.strftime("%d-%m-%Y"),
            birth_date.strftime("%d/%m/%y"),
        ):
            out = out.replace(variant, token)

    return out


def scrub_generic(text: str) -> str:
    """Regex sweep for CPF/CNS/phone/e-mail/date-shaped substrings — no Patient needed."""
    if not text:
        return text
    out = text
    for kind, pattern in _GENERIC_PATTERNS:

        def _repl(m: re.Match, k: str = kind) -> str:
            return _token(k, m.group(0))

        out = pattern.sub(_repl, out)
    return out


def scrub_for_llm(text: str, patient: object | None = None) -> str:
    """Directed patient substitution followed by the generic regex sweep."""
    out = scrub_patient_identifiers(text, patient)
    out = scrub_generic(out)
    return out
