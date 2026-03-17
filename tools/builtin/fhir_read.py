import json
from typing import Any
from urllib.parse import urljoin

import httpx
from httpx import BasicAuth
from pydantic import BaseModel, Field, ValidationError

from config.config import Config
from tools.base import Tool, ToolInvocation, ToolKind, ToolResult


class FHIRReadParams(BaseModel):
    resource_type: str = Field(
        ...,
        description="FHIR resource type to read (e.g., 'Patient', 'Observation', 'Encounter')",
        examples=["Patient", "Observation"],
    )

    resource_id: str = Field(
        ...,
        description="FHIR resource id (logical id) to read",
        examples=["123", "a1b2c3d4"],
    )

    timeout: int = Field(30, ge=5, le=120, description="Request timeout in seconds")

    # Optional: allow conditional reads / format tweaks without changing the core contract
    # (Safe to omit if you want the simplest tool possible.)
    accept: str = Field(
        default="application/fhir+json, application/json;q=0.9, */*;q=0.1",
        description="Accept header value",
    )


class FHIRReadTool(Tool):
    name = "fhir_read"
    description = (
        "Read a specific FHIR resource by type and id. "
        "Returns the full resource body (or OperationOutcome on error)."
    )
    kind = ToolKind.NETWORK
    schema = FHIRReadParams

    def __init__(self, config: Config):
        self.config = config
        self.enabled = True
        self.headers = {
            "Accept-Encoding": "gzip, deflate, br",
        }

        if not getattr(self.config, "fhir", None):
            self.enabled = False

    @staticmethod
    def _clean_path_segment(seg: str) -> str:
        # Avoid accidental leading/trailing slashes causing urljoin surprises
        return (seg or "").strip().strip("/")

    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        try:
            params = FHIRReadParams(**invocation.params)
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

        rt = self._clean_path_segment(params.resource_type)
        rid = self._clean_path_segment(params.resource_id)

        # /<ResourceType>/<id>
        url = urljoin(base, f"{rt}/{rid}")

        headers = dict(self.headers)
        headers["Accept"] = params.accept

        try:
            timeout = httpx.Timeout(params.timeout)
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.get(url, headers=headers, auth=auth)

                # Try to parse JSON, but tolerate non-JSON
                try:
                    payload: Any = response.json()
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

        # Return JSON string when possible
        if isinstance(payload, (dict, list)):
            content = json.dumps(payload, indent=2, ensure_ascii=False)
        else:
            content = str(payload)

        if len(content) > 1000 * 1024:
            content = content[: 1000 * 1024] + "\n... [content truncated]"

        # Helpful metadata
        returned_resource_type = None
        returned_id = None
        warning = None

        if isinstance(payload, dict):
            returned_resource_type = payload.get("resourceType")
            returned_id = payload.get("id")

            # Very small sanity checks (non-fatal)
            if returned_resource_type and returned_resource_type.lower() != rt.lower():
                warning = f"Requested resource_type '{rt}' but got '{returned_resource_type}'."
            if returned_id and returned_id != rid:
                warning = (warning + " " if warning else "") + f"Requested id '{rid}' but got '{returned_id}'."

        return ToolResult.success_result(
            content,
            metadata={
                "status_code": response.status_code,
                "content_length": len(response.content),
                "requested_resource_type": rt,
                "requested_id": rid,
                "returned_resource_type": returned_resource_type,
                "returned_id": returned_id,
                "url": str(response.request.url),
                "warning": warning,
            },
        )