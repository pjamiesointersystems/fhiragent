from typing import Dict, List, Any
from fhir.resources.bundle import Bundle
from fhir.resources.patient import Patient
from fhir.resources.condition import Condition
from fhir.resources.observation import Observation
from fhir.resources.medicationrequest import MedicationRequest
from fhir.resources.encounter import Encounter


class FHIRBundleProcessor:

    def __init__(self, bundle_json: Dict[str, Any]):
        self.bundle = Bundle.model_validate(bundle_json)

        self.patient: Patient | None = None
        self.conditions: List[Condition] = []
        self.observations: List[Observation] = []
        self.medications: List[MedicationRequest] = []
        self.encounters: List[Encounter] = []

        self._separate_resources()

    # -----------------------------
    # Resource separation
    # -----------------------------

    def _separate_resources(self):

        if not self.bundle.entry:
            return

        for entry in self.bundle.entry:

            resource = entry.resource

            if isinstance(resource, Patient):
                self.patient = resource

            elif isinstance(resource, Condition):
                self.conditions.append(resource)

            elif isinstance(resource, Observation):
                self.observations.append(resource)

            elif isinstance(resource, MedicationRequest):
                self.medications.append(resource)

            elif isinstance(resource, Encounter):
                self.encounters.append(resource)

    # -----------------------------
    # Demographics
    # -----------------------------

    def extract_demographics(self):

        if not self.patient:
            return {}

        name = None

        if self.patient.name:
            name = self.patient.name[0].text

        return {
            "name": name,
            "gender": self.patient.gender,
            "birthDate": str(self.patient.birthDate)
        }

    # -----------------------------
    # Conditions
    # -----------------------------

    def extract_conditions(self):

        results = []

        for cond in self.conditions:

            name = None

            if cond.code and cond.code.coding:
                name = cond.code.coding[0].display

            status = None

            if cond.clinicalStatus and cond.clinicalStatus.text:
                status = cond.clinicalStatus.text

            results.append({
                "condition": name,
                "status": status
            })

        return results

    # -----------------------------
    # Observations
    # -----------------------------

    def extract_observations(self):

        results = []

        for obs in self.observations:

            if not obs.valueQuantity:
                continue

            name = None

            if obs.code and obs.code.coding:
                name = obs.code.coding[0].display

            results.append({
                "test": name,
                "value": obs.valueQuantity.value,
                "unit": obs.valueQuantity.unit
            })

        return results

    # -----------------------------
    # Medications
    # -----------------------------

    def extract_medications(self):

        results = []

        for med in self.medications:

            name = None

            if med.medicationCodeableConcept and med.medicationCodeableConcept.coding:
                name = med.medicationCodeableConcept.coding[0].display

            results.append({
                "medication": name,
                "status": med.status
            })

        return results

    # -----------------------------
    # Encounters
    # -----------------------------

    def extract_encounters(self):

        results = []

        for enc in self.encounters:

            encounter_type = None

            if enc.type and enc.type[0].coding:
                encounter_type = enc.type[0].coding[0].display

            results.append({
                "type": encounter_type,
                "status": enc.status
            })

        return results

    # -----------------------------
    # Build compact clinical summary
    # -----------------------------

    def build_clinical_summary(self):

        return {
            "patient": self.extract_demographics(),
            "conditions": self.extract_conditions(),
            "observations": self.extract_observations(),
            "medications": self.extract_medications(),
            "encounters": self.extract_encounters()
        }