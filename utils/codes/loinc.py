from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, Optional


LOINC_SYSTEM_URI = "http://loinc.org"


def _normalize(text: str) -> str:
    """
    Normalize a term for robust matching:
    - lowercase
    - trim
    - remove punctuation
    - collapse whitespace
    """
    if text is None:
        return ""
    text = text.strip().lower()
    # Replace non-alphanumeric with spaces, then collapse spaces
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


@dataclass
class LoincLookup:
    """
    In-memory Loinc lookup suitable for agent tooling.
    - lookup(term) -> "http://loinc.org/sct|{code}" or None
    - add_term(term, code) -> None (adds/overwrites term)
    """
    _term_to_code: Dict[str, str] = field(default_factory=dict)

    @classmethod
    def with_default_common_terms(cls) -> "LoincLookup":
        """
        Seed with the common terms from your demo list.
        NOTE: If you change the list, also update aliases below.
        """
        inst = cls()

        # Core entries: normalized_term -> code
        defaults = {
            "blood pressure panel": "35094-2.",
            "systolic blood pressure": "8480-6",
            "diastolic blood pressure": "8462-4",
            "heart rate": "8867-4",
        }

        for term, code in defaults.items():
            inst.add_term(term, code)

        return inst

    def lookup(self, term: str) -> Optional[str]:
        """
        Look up a LOINC code by term and return it as:
            "http://loinc.org/sct|{code}"
        Return None if not found.
        """
        key = _normalize(term)
        if not key:
            return None

        code = self._term_to_code.get(key)
        if code:
            return f"{LOINC_SYSTEM_URI}|{code}"
        return None

    def add_term(self, term: str, code: str) -> None:
        """
        Add or overwrite a term -> SNOMED code mapping.
        Stores in normalized form for case/punctuation-insensitive matching.
        """
        key = _normalize(term)
        if not key:
            raise ValueError("term must be a non-empty string")

        code_str = str(code).strip()
        if not code_str:
            raise ValueError("code must be a non-empty string")

        self._term_to_code[key] = code_str

    def has_term(self, term: str) -> bool:
        return _normalize(term) in self._term_to_code


# Convenience singleton for agent tools
DEFAULT_LOINC = LoincLookup.with_default_common_terms()

def lookup_loinc(term: str) -> Optional[str]:
    """
    Function-style wrapper (handy for agent tool registration).
    """
    return DEFAULT_LOINC.lookup(term)


def add_loinc(term: str, code: str) -> None:
    """
    Function-style wrapper (handy for agent tool registration).
    """
    DEFAULT_LOINC.add_term(term, code)