import json
from typing import Any
from urllib.parse import urljoin

import httpx
from httpx import BasicAuth
from pydantic import BaseModel, Field, ValidationError

from config.config import Config
from tools.base import Tool, ToolInvocation, ToolKind, ToolResult

from clinical.fhir_bundle_processor import FHIRBundleProcessor

class FHIREverythingParams(BaseModel):
    patient_id: str = Field(
        ...,
        description="FHIR Patient logical id",
        examples=["123", "example-patient"],
    )

    timeout: int = Field(
        60,
        ge=5,
        le=180,
        description="Request timeout in seconds"
    )

    accept: str = Field(
        default="application/fhir+json, application/json;q=0.9, */*;q=0.1",
        description="Accept header value",
    )


class FHIREverythingTool(Tool):
    name = "fhir_everything"

    description = (
        "Retrieve all resources related to a patient using the FHIR "
        "$everything operation. Returns a Bundle containing the patient's "
        "complete clinical record."
    )

    kind = ToolKind.NETWORK
    schema = FHIREverythingParams

    def __init__(self, config: Config):
        self.config = config
        self.enabled = True

        self.headers = {
            "Accept-Encoding": "gzip, deflate, br",
        }

        if not getattr(self.config, "fhir", None):
            self.enabled = False

    @staticmethod
    def _clean(seg: str) -> str:
        return (seg or "").strip().strip("/")

    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        try:
            params = FHIREverythingParams(**invocation.params)
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
                return ToolResult.error_result(
                    "BasicAuth requires fhir.username and fhir.password"
                )

            auth = BasicAuth(username, password)

        base = fhir.base_url.rstrip("/") + "/"

        patient_id = self._clean(params.patient_id)

        # FHIR operation endpoint
        url = urljoin(base, f"Patient/{patient_id}/$everything")

        headers = dict(self.headers)
        headers["Accept"] = params.accept

        try:
            timeout = httpx.Timeout(params.timeout)

            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.get(url, headers=headers, auth=auth)

                try:
                    payload: Any = response.json()
                    # Parse the bundle
                    if isinstance(payload, dict) and payload.get("resourceType") == "Bundle":

                        from clinical.fhir_bundle_processor import FHIRBundleProcessor

                        processor = FHIRBundleProcessor(payload)

                        clinical_summary = processor.build_clinical_summary()

                        content = json.dumps(clinical_summary, indent=2)

                    else:
                        content = json.dumps(payload, indent=2)
                except ValueError:
                    payload = response.text

                response.raise_for_status()

        except httpx.HTTPStatusError as e:
            return ToolResult.error_result(
                f"""
HTTP {e.response.status_code}: {e.response.reason_phrase}

Request URL:
{e.request.url}

Response Body:
{e.response.text}
""".strip()
            )

        except httpx.RequestError as e:
            return ToolResult.error_result(
                f"Network error contacting FHIR server: {e}"
            )

        if isinstance(payload, (dict, list)):
            content = json.dumps(payload, indent=2, ensure_ascii=False)
        else:
            content = str(payload)

        # avoid giant responses crashing the agent
        if len(content) > 1000 * 1024:
            content = content[:1000 * 1024] + "\n... [content truncated]"

        entry_count = None
        bundle_type = None

        if isinstance(payload, dict):
            bundle_type = payload.get("type")
            entry_count = len(payload.get("entry", []))

        return ToolResult.success_result(
            content,
            metadata={
                "url": str(response.request.url),
                "status_code": response.status_code,
                "bundle_type": bundle_type,
                "entry_count": entry_count,
                "content_length": len(response.content),
                "patient_id": patient_id,
            },
        )