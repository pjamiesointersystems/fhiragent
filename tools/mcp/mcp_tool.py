import json
from typing import Any
from config.config import Config
from tools.base import Tool, ToolInvocation, ToolKind, ToolResult
from tools.mcp.client import MCPClient, MCPToolInfo
from utils.codes.snomed import lookup_snomed
from utils.paths import resolve_path


class MCPTool(Tool):

    def __init__(
        self,
        config: Config,
        client: MCPClient,
        tool_info: MCPToolInfo,
        name: str,
    ) -> None:
        super().__init__(config)
        self._tool_info = tool_info
        self._client = client
        self.name = name
        self.description = self._tool_info.description

    @property
    def schema(self) -> dict[str, Any]:
        input_schema = self._tool_info.input_schema or {}
        return {
            "type": "object",
            "properties": input_schema.get("properties", {}),
            "required": input_schema.get("required", []),
        }

    def is_mutating(self, params) -> bool:
        return True

    kind = ToolKind.MCP

    @staticmethod
    def _should_fallback_to_local_snomed(error_text: str) -> bool:
        normalized = (error_text or "").lower()
        return any(
            marker in normalized
            for marker in (
                "snomed ct api error",
                "status code 503",
                "status code 410",
                "econnreset",
                "etimedout",
                "network error",
                "service unavailable",
            )
        )

    def _local_snomed_fallback(self, invocation: ToolInvocation, error_text: str) -> ToolResult | None:
        if self._tool_info.name != "snomed_search":
            return None
        if not self._should_fallback_to_local_snomed(error_text):
            return None

        query = str(invocation.params.get("query", "")).strip()
        if not query:
            return None

        resolved_token = lookup_snomed(query)
        if not resolved_token:
            return None

        code = resolved_token.split("|", 1)[1] if "|" in resolved_token else resolved_token
        payload = {
            "query": query,
            "fallback_used": True,
            "fallback_source": "utils.codes.snomed",
            "resolved_token": resolved_token,
            "system": "http://snomed.info/sct",
            "code": code,
            "display": query,
            "note": (
                "Used local SNOMED fallback because MCP SNOMED API was unavailable. "
                "Code comes from in-repo lookup table."
            ),
            "original_error": error_text,
        }
        return ToolResult.success_result(json.dumps(payload, indent=2))

    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        try:
            result = await self._client.call_tool(
                self._tool_info.name,
                invocation.params,
            )
            output = result.get("output", "")
            is_error = result.get("is_error", False)

            if is_error:
                fallback = self._local_snomed_fallback(invocation, output)
                if fallback:
                    return fallback
                return ToolResult.error_result(output)

            return ToolResult.success_result(output)
        except Exception as e:
            error_text = f"MCP tool failed: {e}"
            fallback = self._local_snomed_fallback(invocation, error_text)
            if fallback:
                return fallback
            return ToolResult.error_result(error_text)