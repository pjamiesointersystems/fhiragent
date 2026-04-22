# snomed.py
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, Optional


SNOMED_SYSTEM_URI = "http://snomed.info/sct"


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
class SnomedLookup:
    """
    In-memory SNOMED lookup suitable for agent tooling.
    - lookup(term) -> "http://snomed.info/sct|{code}" or None
    - add_term(term, code) -> None (adds/overwrites term)
    """
    _term_to_code: Dict[str, str] = field(default_factory=dict)

    @classmethod
    def with_default_common_terms(cls) -> "SnomedLookup":
        """
        Seed with the common terms from your demo list.
        NOTE: If you change the list, also update aliases below.
        """
        inst = cls()

        # Core entries: normalized_term -> code
        defaults = {
            "hypertension": "38341003",
            "type 2 diabetes": "44054006",
            "type 2 diabetes mellitus": "44054006",
            "diabetes mellitus type 2": "44054006",
            "type two diabetes mellitus": "44054006",
            "diabetes mellitus type two": "44054006",
            "asthma": "195967001",
            "acute upper respiratory infection": "47505003",
            "back pain": "279039007",
            "osteoarthritis": "396275006",
            "depression": "35489007",
            "anxiety disorder": "48694002",
            "hyperlipidemia": "55822004",
            "gastroesophageal reflux disease": "235719002",
            "gerd": "235719002",
            "acute bronchitis": "10509002",
            "pneumonia": "233604007",
            "chronic obstructive pulmonary disease": "13645005",
            "copd": "13645005",
            "heart failure": "84114007",
            "ischemic heart disease": "414545008",
            "acute myocardial infarction": "22298006",
            "myocardial infarction": "22298006",
            "stroke": "230690007",
            "urinary tract infection": "68566005",
            "uti": "68566005",
            "atrial fibrillation": "49436004",
            "migraine": "37796009",
            "hypothyroidism": "40930008",
            "chronic kidney disease": "709044004",
            "ckd": "709044004",
            "anemia": "271737000",
            "acute pharyngitis": "370135005",
            "sinusitis": "34100007",
            "allergic rhinitis": "418471000000107",
            "conjunctivitis": "65363002",
            "low back pain": "279039007",
            "sprain of ankle": "284470004",
            "fever": "386661006",
            "cough": "49727002",
            "acute gastroenteritis": "11545007",
            "constipation": "14760008",
            "diarrhea": "62315008",
            "obesity": "414916001",
            "acute otitis media": "10509002",  # if you prefer, replace with an otitis media concept you use
            "dermatitis": "444814009",
            "cellulitis": "418304008",
            "tonsillitis": "38069000",
            "sepsis": "91302008",
            "peptic ulcer disease": "72359000",
            "pancreatitis": "197456005",
            "mood disorder": "126952008",
            "bipolar disorder": "13746004",
            "schizophrenia": "58214004",
            "substance abuse": "160603005",
            "acute kidney injury": "315295000",
            "aki": "315295000",
            "chronic liver disease": "404846005",
            "hepatitis c infection": "235856003",
            "hepatitis c": "235856003",
            "hiv infection": "86406008",
            "hypoxia": "409782003",
            "pneumothorax": "233738009",
            "fracture of femur": "125605004",
            "fracture of wrist": "125605004",
            "gout": "7439002",
            "rheumatoid arthritis": "69896004",
            "psoriasis": "9014002",
            "celiac disease": "19262009",
            "irritable bowel syndrome": "235721009",
            "ibs": "235721009",
            "chronic sinusitis": "36989005",
            "sleep apnea": "73430006",
            "cataract": "11687002",
            "glaucoma": "13684000",
            "hearing loss": "36962004",
            "vertigo": "442311008",
            "acute appendicitis": "74400008",
            "cholelithiasis": "235710007",
            "gallstones": "235710007",
            "bursitis": "32133005",
            "tendinitis": "317009",  # update if you want a different tendonitis concept
            "varicose veins": "312912005",
            "deep vein thrombosis": "59282003",
            "dvt": "59282003",
            "pulmonary embolism": "443412003",
            "pe": "443412003",
            "hyperthyroidism": "34486009",
            "ptsd": "47505003",  # update if you want a PTSD-specific concept
            "adhd": "192127007",
            "autism spectrum disorder": "60578009",
            "osteoporosis": "64859006",
            "benign prostatic hyperplasia": "154283005",
            "bph": "154283005",
            "urinary incontinence": "68566005",  # update if you want an incontinence-specific concept
            "erectile dysfunction": "52702003",
            "menopause": "32214001",
            "pregnancy": "77386006",
            "labor": "261005008",
            "childbirth": "261005008",
            "pre eclampsia": "414166001",
            "preeclampsia": "414166001",
            "gestational diabetes": "44054006",  # update if you want gestational diabetes-specific concept
            "carpal tunnel syndrome": "40956009",
            "alzheimer disease": "26929004",
            "alzheimers disease": "26929004",
            "parkinson disease": "49049000",
            "multiple sclerosis": "24700007",
            "epilepsy": "84757009",
            "brain tumor": "93890001",
            "intracranial neoplasm": "93890001",
            "covid 19": "840539006",
            "influenza": "6142004",
            "bronchiectasis": "281867008",
            "cystic fibrosis": "19043007",
            "sickle cell disease": "90688005",
            "thalassemia": "30281000119106",
            "lupus erythematosus": "55464009",
            "systemic lupus erythematosus": "55464009",
            "lyme disease": "102098004",
            "tuberculosis": "56717001",
        }

        for term, code in defaults.items():
            inst.add_term(term, code)

        return inst

    def lookup(self, term: str) -> Optional[str]:
        """
        Look up a SNOMED code by term and return it as:
            "http://snomed.info/sct|{code}"
        Return None if not found.
        """
        key = _normalize(term)
        if not key:
            return None

        code = self._term_to_code.get(key)
        if code:
            return f"{SNOMED_SYSTEM_URI}|{code}"
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
DEFAULT_SNOMED = SnomedLookup.with_default_common_terms()


def lookup_snomed(term: str) -> Optional[str]:
    """
    Function-style wrapper (handy for agent tool registration).
    """
    return DEFAULT_SNOMED.lookup(term)


def add_snomed(term: str, code: str) -> None:
    """
    Function-style wrapper (handy for agent tool registration).
    """
    DEFAULT_SNOMED.add_term(term, code)