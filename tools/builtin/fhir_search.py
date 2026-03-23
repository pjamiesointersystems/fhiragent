import json
from enum import Enum
from typing import Any
from urllib.parse import parse_qsl, urljoin

import httpx
from httpx import BasicAuth
from pydantic import BaseModel, Field, ValidationError

from config.config import Config
from tools.base import Tool, ToolInvocation, ToolKind, ToolResult
from utils.codes.loinc import lookup_loinc
from utils.codes.rxnorm import lookup_rxnorm
from utils.codes.snomed import lookup_snomed


class ClinicalDomain(str, Enum):
    condition = "condition"
    observation = "observation"
    medicationrequest = "medicationrequest"
    allergy = "allergy"


class FHIRSearchParams(BaseModel):
    resource_type: str = Field(
        ...,
        description="FHIR resource type to search (e.g., 'Patient', 'Observation', 'Encounter', 'MedicationRequest')",
        examples=["Patient", "Observation"],
    )

    # LLM-friendly: key/value map
    search: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "FHIR search parameters as key/value pairs. "
            "Example: {'name': 'Smith', 'gender': 'female', '_count': '10'}"
        ),
    )

    # Optional escape hatch for power users
    query_string: str | None = Field(
        default=None,
        description=(
            "Optional raw query string like 'name=Smith&gender=female'. "
            "If provided, merged with 'search' (search wins on conflicts). "
            "Do NOT include leading '?', and do NOT include the resource type."
        ),
    )

    timeout: int = Field(30, ge=5, le=120, description="Request timeout in seconds")
    max_results: int = Field(10, ge=1, le=200, description="Maximum results to return")

    resolved_token: str | None = Field(
        default=None,
        description=(
            "Pre-resolved terminology token in 'system|code' format, e.g. "
            "'http://snomed.info/sct|709044004'. "
            "Use this after resolving a clinical term via MCP terminology tools. "
            "When provided with clinical_domain and resource_type=Patient, triggers "
            "_has reverse-chaining to find patients with matching conditions/observations/medicationrequests."
        ),
    )

    clinical_domain: ClinicalDomain | None = Field(
        default=None,
        description=(
            "Indicates the type of clinical concept for terminology resolution. "
            "Exact values: 'condition' (diagnoses/problems, SNOMED CT), 'observation' (labs/vitals, LOINC), "
            "'medicationrequest' (drugs/medications/prescriptions, RxNorm — NOT 'medication'), "
            "'allergy' (allergy intolerances, SNOMED CT)."
        ),
    )

    follow_reverse: bool = Field(
        default=True,
        description=(
            "If true and resource_type is a parent resource (especially Patient), rewrite cohort-style requests "
            "like 'patients with <condition/observation/medicationrequest/allergy>' to use FHIR reverse-chaining "
            "with the _has parameter. When resource_type is Patient and a clinical_domain is provided, "
            "do NOT use code= on Patient; use _has instead."
        ),
    )

    def build_query_params(self) -> dict[str, str]:
        """Merge query_string + search, then enforce _count <= max_results."""
        qp: dict[str, str] = {}

        if self.query_string:
            qp.update({k: v for (k, v) in parse_qsl(self.query_string, keep_blank_values=True)})

        qp.update(self.search or {})

        requested_count: int | None = None
        if "_count" in qp:
            try:
                requested_count = int(qp["_count"])
            except ValueError:
                requested_count = None

        if requested_count is None:
            qp["_count"] = str(self.max_results)
        else:
            qp["_count"] = str(min(requested_count, self.max_results))

        return qp


class FHIRSearchTool(Tool):
    name = "fhir_search"
    description = "Search a FHIR repository for resources. Returns a searchset bundle (or OperationOutcome on error)."
    kind = ToolKind.NETWORK
    schema = FHIRSearchParams

    def __init__(self, config: Config):
        self.config = config
        self.enabled = True
        self.headers = {
            "Accept": "*/*",
            "Accept-Encoding": "gzip, deflate, br",
        }

        if not self.config.fhir:
            self.enabled = False

    @staticmethod
    def _apply_reverse_chaining(
        resource_type: str,
        clinical_domain: ClinicalDomain | None,
        follow_reverse: bool,
        query_params: dict[str, str],
        token: str | None,
    ) -> dict[str, str]:
        """Rewrite Patient cohort queries to use _has reverse chaining."""
        qp = dict(query_params)

        if not follow_reverse:
            return qp
        if (resource_type or "").lower() != "patient":
            return qp
        if not token:
            return qp

        # Auto-detect clinical domain from token URL if not explicitly provided
        if clinical_domain is None:
            if "snomed.info/sct" in token:
                clinical_domain = ClinicalDomain.condition
            elif "loinc.org" in token:
                clinical_domain = ClinicalDomain.observation
            elif "rxnorm" in token or "nlm.nih.gov" in token:
                clinical_domain = ClinicalDomain.medicationrequest

        if clinical_domain is None:
            return qp

        # If user already provided an explicit _has, do nothing
        if any(str(k).startswith("_has:") for k in qp.keys()):
            return qp

        # Never use 'code' directly on Patient for these cohort queries
        qp.pop("code", None)

        if clinical_domain == ClinicalDomain.condition:
            qp["_has:Condition:patient:code"] = token
        elif clinical_domain == ClinicalDomain.allergy:
            qp["_has:AllergyIntolerance:patient:code"] = token
        elif clinical_domain == ClinicalDomain.observation:
            qp["_has:Observation:subject:code"] = token
        elif clinical_domain == ClinicalDomain.medicationrequest:
            # Server/profile dependent. Start with MedicationRequest.
            qp["_has:MedicationRequest:subject:code"] = token

        return qp

    @staticmethod
    def _is_param_not_supported_operation_outcome(payload: object, param_name: str) -> bool:
        """Detect InterSystems-style OperationOutcome for unsupported parameter."""
        if not isinstance(payload, dict):
            return False
        if payload.get("resourceType") != "OperationOutcome":
            return False

        issues = payload.get("issue") or []
        if not isinstance(issues, list):
            return False

        for issue in issues:
            if not isinstance(issue, dict):
                continue
            diagnostics = str(issue.get("diagnostics") or "")
            details = issue.get("details") or {}
            text = str(details.get("text") or "") if isinstance(details, dict) else ""
            if "ParameterNotSupported" in diagnostics and f"'{param_name}'" in text:
                return True

        return False

    @classmethod
    def _bundle_contains_param_not_supported(cls, payload: object, param_name: str) -> bool:
        """Some servers return a Bundle containing an OperationOutcome entry."""
        if not isinstance(payload, dict) or payload.get("resourceType") != "Bundle":
            return False
        entries = payload.get("entry") or []
        if not isinstance(entries, list):
            return False
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            res = entry.get("resource")
            if cls._is_param_not_supported_operation_outcome(res, param_name):
                return True
        return False

    async def execute(self, invocation: ToolInvocation) -> ToolResult:

        reverse_chaining_used = False
        reverse_chaining_param_key = None
        try:
            params = FHIRSearchParams(**invocation.params)
        except (ValidationError, ValueError) as e:
            return ToolResult.error_result(f"Invalid tool parameters:\n{e}")

        fhir = getattr(self.config, "fhir", None)
        if not fhir or not getattr(fhir, "base_url", None):
            return ToolResult.error_result(
                "FHIR config missing or base_url not set. Add a [fhir] section in config.toml."
            )

        auth = None
        if getattr(fhir, "auth", None) == "BasicAuth":
            username = fhir.resolved_username()
            password = fhir.resolved_password()
            if not username or not password:
                return ToolResult.error_result("BasicAuth requires fhir.username and fhir.password")
            auth = BasicAuth(username, password)

        base = fhir.base_url.rstrip("/") + "/"
        url = urljoin(base, params.resource_type)

        headers = dict(self.headers)

        query_params = params.build_query_params()

        # Use pre-resolved token from MCP terminology tools (passed in by the LLM)
        token: str | None = params.resolved_token

        # Apply reverse chaining FIRST for Patient cohorts
        query_params = self._apply_reverse_chaining(
            resource_type=params.resource_type,
            clinical_domain=params.clinical_domain,
            follow_reverse=params.follow_reverse,
            query_params=query_params,
            token=token,
        )

        # If not using _has, and we have a token, set the conventional code search parameter
        if token and not any(k.startswith("_has:") for k in query_params.keys()):
            query_params.setdefault("code", token)

        full_url = httpx.URL(url, params=query_params)

        try:
            timeout = httpx.Timeout(params.timeout)
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.get(url, params=query_params, headers=headers, auth=auth)

                # Try to parse JSON, but tolerate non-JSON
                try:
                    payload: Any = response.json()
                except ValueError:
                    payload = response.text

                # If server says the parameter is unsupported, retry once with _has (Patient cohort only)
                unsupported_code = False
                if isinstance(payload, dict):
                    unsupported_code = (
                        self._is_param_not_supported_operation_outcome(payload, "code")
                        or self._bundle_contains_param_not_supported(payload, "code")
                    )

                if (
                    params.follow_reverse
                    and (params.resource_type or "").lower() == "patient"
                    and token
                    and ("code" in query_params)
                    and unsupported_code
                ):
                    query_params_retry = self._apply_reverse_chaining(
                        resource_type=params.resource_type,
                        clinical_domain=params.clinical_domain,
                        follow_reverse=True,
                        query_params=query_params,
                        token=token,
                    )

                    response = await client.get(url, params=query_params_retry, headers=headers, auth=auth)
                    full_url = httpx.URL(url, params=query_params_retry)
                    try:
                        payload = response.json()
                    except ValueError:
                        payload = response.text

                response.raise_for_status()

        except httpx.HTTPStatusError as e:
            return ToolResult.error_result(
                f"""
HTTP {e.response.status_code}: {e.response.reason_phrase}

Request URL:
{e.request.url}

Request Headers:
{dict(e.request.headers)}

Response Headers:
{dict(e.response.headers)}

Response Body:
{e.response.text}
""".strip()
            )
        except httpx.RequestError as e:
            return ToolResult.error_result(f"Network error contacting FHIR server: {e}")

        # Bundle metadata
        entry_count = None
        bundle_type = None
        total = None
        if isinstance(payload, dict) and payload.get("resourceType") == "Bundle":
            bundle_type = payload.get("type")
            total = payload.get("total")
            entries = payload.get("entry") or []
            entry_count = len(entries) if isinstance(entries, list) else 0

        # Return JSON string when possible
        if isinstance(payload, (dict, list)):
            content = json.dumps(payload, indent=2, ensure_ascii=False)
        else:
            content = str(payload)

        if len(content) > 1000 * 1024:
            content = content[: 1000 * 1024] + "\n... [content truncated]"

        warning = None
        if bundle_type is not None and bundle_type != "searchset":
            warning = f"Expected Bundle.type='searchset' but got '{bundle_type}'."

        # after you rewrite:
        if any(k.startswith("_has:") for k in query_params.keys()):
            reverse_chaining_used = True
            reverse_chaining_param_key = next(k for k in query_params.keys() if k.startswith("_has:"))

        return ToolResult.success_result(
            content,
            metadata={
                "status_code": response.status_code,
                "content_length": len(response.content),
                "resource_type": params.resource_type,
                "url": str(full_url),
                "requested_count": query_params.get("_count"),
                "reverse_chaining": reverse_chaining_used,    # bool
                "reverse_chaining_param": reverse_chaining_param_key,  # e.g. "_has:Condition:patient:code"
                "resolved_token": token,                      # e.g. "http://snomed.info/sct|44054006"
                "bundle_type": bundle_type,
                "entry_count": entry_count,
                "total": total,
                "warning": warning,
            },
        )
