from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, Optional


RXNORM_SYSTEM_URI = "http://rxnorm.org"


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
class RXNORMLookup:
    """
    In-memory RxNorm lookup suitable for agent tooling.
    - lookup(term) -> "http://www.nlm.nih.gov/research/umls/rxnorm|{code}" or None
    - add_term(term, code) -> None (adds/overwrites term)
    """
    _term_to_code: Dict[str, str] = field(default_factory=dict)

    @classmethod
    def with_default_common_terms(cls) -> "RXNORMLookup":
        """
        Seed with the common terms from your demo list.
        NOTE: If you change the list, also update aliases below.
        """
        inst = cls()

        # Core entries: normalized_term -> code
        defaults = {
            "aspirin 81 MG Delayed Release Oral Tablet": "308416",
            "metformin hydrochloride 1000 MG": "861014",
        }

        for term, code in defaults.items():
            inst.add_term(term, code)

        return inst

    def lookup(self, term: str) -> Optional[str]:
        """
        Look up a RXNORM code by term and return it as:
            "http://www.nlm.nih.gov/research/umls/rxnorm|{code}"
        Return None if not found.
        """
        key = _normalize(term)
        if not key:
            return None

        code = self._term_to_code.get(key)
        if code:
            return f"{RXNORM_SYSTEM_URI}|{code}"
        return None

    def add_term(self, term: str, code: str) -> None:
        """
        Add or overwrite a term -> RxNorm code mapping.
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
DEFAULT_RXNORM = RXNORMLookup.with_default_common_terms()

def lookup_rxnorm(term: str) -> Optional[str]:
    """
    Function-style wrapper (handy for agent tool registration).
    """
    return DEFAULT_RXNORM.lookup(term)


def add_rxnorm(term: str, code: str) -> None:
    """
    Function-style wrapper (handy for agent tool registration).
    """
    DEFAULT_RXNORM.add_term(term, code)