# fhir_update.py
import json
from typing import Any, Tuple
from urllib.parse import urljoin

import httpx
from httpx import BasicAuth
from pydantic import BaseModel, Field, ValidationError

from config.config import Config
from tools.base import Tool, ToolConfirmation, ToolInvocation, ToolKind, ToolResult


class FHIRUpdateParams(BaseModel):
    resource_type: str = Field(..., description="FHIR resource type (e.g., 'Patient')")
    resource_id: str = Field(..., description="Logical id of the resource to update")
    element_path: str = Field(
        ...,
        description=(
            "Dot-separated path into the resource JSON where substitution should occur. "
            "Example: 'identifier.system' or 'telecom.value' or 'name.given'. "
            "If an intermediate node is an array, the tool will iterate array members."
        ),
    )
    old_value: Any = Field(..., description="The exact value to replace (primitive or JSON-serializable object)")
    new_value: Any = Field(..., description="Replacement value (must be JSON-serializable)")
    timeout: int = Field(30, ge=5, le=120, description="Request timeout in seconds")
    accept: str = Field(
        default="application/fhir+json, application/json;q=0.9, */*;q=0.1",
        description="Accept header value for requests",
    )


class FHIRUpdateTool(Tool):
    name = "fhir_update"
    description = (
        "Read a FHIR resource by type/id, substitute old_value -> new_value at element_path, "
        "and perform a PUT update with the replaced resource body."
    )
    kind = ToolKind.NETWORK
    schema = FHIRUpdateParams

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
        return (seg or "").strip().strip("/")

    @staticmethod
    def _equals(a: Any, b: Any) -> bool:
        """Robust equality check for primitives and JSON-like objects."""
        try:
            if isinstance(a, (str, int, float, bool, type(None))) and isinstance(
                b, (str, int, float, bool, type(None))
            ):
                return a == b
            # Fallback: structural JSON comparison
            return json.dumps(a, sort_keys=True, ensure_ascii=False) == json.dumps(
                b, sort_keys=True, ensure_ascii=False
            )
        except Exception:
            return a == b

    def _substitute_in_node(self, node: Any, parts: list[str], old_val: Any, new_val: Any) -> int:
        """
        Recursively traverse `node` following `parts`.
        When parts is empty, compare node to old_val and replace in-place by returning new node value via caller.
        Returns number of substitutions performed under this node (modifies node in-place for dict/list cases).
        """
        if not parts:
            # Should not get here for root call (we always use at least one path segment),
            # but handle defensively: nothing to do here.
            return 0

        head, *tail = parts

        # If the current node is a list, apply same path to every element
        if isinstance(node, list):
            total = 0
            for idx, item in enumerate(node):
                # if tail empty and head is numeric index? We're treating head as key only.
                # descend into each list item with the full parts (head still used when item is dict)
                total += self._substitute_in_node(item, parts, old_val, new_val)
            return total

        # If node is a dict, advance into head key
        if isinstance(node, dict):
            if head not in node:
                # key missing -> nothing to substitute here
                return 0

            if not tail:
                # Target reached: node[head] may be primitive, dict or list
                target = node[head]
                substitutions = 0

                if isinstance(target, list):
                    # Iterate list items and replace those that match old_val
                    for i, v in enumerate(target):
                        if self._equals(v, old_val):
                            target[i] = new_val
                            substitutions += 1
                        else:
                            # If list items are dict/complex, attempt deep substitution (replace nested fields)
                            if isinstance(v, (dict, list)):
                                substitutions += self._substitute_in_node(v, [], old_val, new_val)
                    node[head] = target
                    return substitutions

                else:
                    # primitive or object: compare and replace if equal (object equality via JSON)
                    if self._equals(target, old_val):
                        node[head] = new_val
                        return 1
                    # If target is dict, attempt to recurse into its children with empty tail:
                    if isinstance(target, dict):
                        # nothing more specific requested -> no substitution
                        return 0
                    return 0

            # tail is not empty: descend further
            child = node[head]
            return self._substitute_in_node(child, tail, old_val, new_val)

        # node is primitive and we still have parts -> can't descend
        return 0

    async def get_confirmation(
        self, invocation: ToolInvocation
    ) -> ToolConfirmation | None:
        params = FHIRUpdateParams(**invocation.params)
        path = None

        action = "Updated" 

        return ToolConfirmation(
            tool_name=self.name,
            params=invocation.params,
            description=f"{action}",
            diff=None,
            #affected_paths=[path],
            is_dangerous=True,
        )

    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        try:
            params = FHIRUpdateParams(**invocation.params)
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
        url = urljoin(base, f"{rt}/{rid}")

        headers = dict(self.headers)
        headers["Accept"] = params.accept
        headers["Content-Type"] = "application/fhir+json"

        # Step 1: Read the existing resource
        try:
            timeout = httpx.Timeout(params.timeout)
            async with httpx.AsyncClient(timeout=timeout) as client:
                get_resp = await client.get(url, headers=headers, auth=auth)
                try:
                    resource_payload: Any = get_resp.json()
                except ValueError:
                    return ToolResult.error_result("FHIR read returned non-JSON payload; aborting update.")

                get_resp.raise_for_status()
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

        # Sanity checks
        if not isinstance(resource_payload, dict):
            return ToolResult.error_result("FHIR read did not return a resource object; aborting update.")

        # Step 2: Perform substitution
        parts = [p for p in params.element_path.split(".") if p]
        if not parts:
            return ToolResult.error_result("element_path is empty after parsing; provide a valid dot-separated path.")

        # Work on a deep copy to avoid mutating the original payload in-place (defensive)
        try:
            working = json.loads(json.dumps(resource_payload))  # cheap deep copy via json roundtrip
        except Exception:
            # fallback shallow copy
            working = dict(resource_payload)

        replacements = self._substitute_in_node(working, parts, params.old_value, params.new_value)

        if replacements == 0:
            return ToolResult.error_result(
                f"No occurrences of the specified old_value were found at path '{params.element_path}'. No update performed."
            )

        # Step 3: PUT the updated resource
        try:
            timeout = httpx.Timeout(params.timeout)
            async with httpx.AsyncClient(timeout=timeout) as client:
                put_resp = await client.put(url, headers=headers, auth=auth, json=working)
                try:
                    put_payload = put_resp.json()
                except ValueError:
                    put_payload = put_resp.text

                put_resp.raise_for_status()
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
            return ToolResult.error_result(f"Network error contacting FHIR server during update: {e}")

        # Return success with metadata
        content = json.dumps(put_payload, indent=2, ensure_ascii=False) if isinstance(put_payload, (dict, list)) else str(put_payload)
        if len(content) > 1000 * 1024:
            content = content[: 1000 * 1024] + "\n... [content truncated]"

        return ToolResult.success_result(
            content,
            metadata={
                "status_code": put_resp.status_code,
                "resource_type": rt,
                "resource_id": rid,
                "element_path": params.element_path,
                "replacements": replacements,
                "url": str(put_resp.request.url),
            },
        )