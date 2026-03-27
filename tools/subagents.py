import asyncio
from typing import Any
from config.config import Config
from tools.base import Tool, ToolInvocation, ToolResult
from dataclasses import dataclass
from pydantic import BaseModel, Field


class SubagentParams(BaseModel):
    goal: str = Field(
        ..., description="The specific task or goal for the subagent to accomplish"
    )


@dataclass
class SubagentDefinition:
    name: str
    description: str
    goal_prompt: str
    allowed_tools: list[str] | None = None
    max_turns: int = 20
    timeout_seconds: float = 600


class SubagentTool(Tool):
    def __init__(self, config: Config, definition: SubagentDefinition):
        super().__init__(config)
        self.definition = definition

    @property
    def name(self) -> str:
        return f"subagent_{self.definition.name}"

    @property
    def description(self) -> str:
        return f"subagent_{self.definition.description}"

    schema = SubagentParams

    def is_mutating(self, params: dict[str, Any]) -> bool:
        return True

    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        from agent.agent import Agent
        from agent.events import AgentEventType

        params = SubagentParams(**invocation.params)
        if not params.goal:
            return ToolResult.error_result("No goal specified for sub-agent")

        config_dict = self.config.to_dict()
        config_dict["max_turns"] = self.definition.max_turns
        if self.definition.allowed_tools:
            config_dict["allowed_tools"] = self.definition.allowed_tools

        subagent_config = Config(**config_dict)

        prompt = f"""You are a specialized sub-agent with a specific task to complete.

        {self.definition.goal_prompt}

        YOUR TASK:
        {params.goal}

        IMPORTANT:
        - Focus only on completing the specified task
        - Do not engage in unrelated actions
        - Once you have completed the task or have the answer, provide your final response
        - Be concise and direct in your output
        """

        tool_calls = []
        final_response = None
        error = None
        terminate_response = "goal"

        try:
            async with Agent(subagent_config) as agent:
                deadline = (
                    asyncio.get_event_loop().time() + self.definition.timeout_seconds
                )

                async for event in agent.run(prompt):
                    if asyncio.get_event_loop().time() > deadline:
                        terminate_response = "timeout"
                        final_response = "Sub-agent timed out"
                        break

                    if event.type == AgentEventType.TOOL_CALL_START:
                        tool_calls.append(event.data.get("name"))
                    elif event.type == AgentEventType.TEXT_COMPLETE:
                        final_response = event.data.get("content")
                    elif event.type == AgentEventType.AGENT_END:
                        if final_response is None:
                            final_response = event.data.get("response")
                    elif event.type == AgentEventType.AGENT_ERROR:
                        terminate_response = "error"
                        error = event.data.get("error", "Unknown")
                        final_response = f"Sub-agent error: {error}"
                        break
        except Exception as e:
            terminate_response = "error"
            error = str(e)
            final_response = f"Sub-agent failed: {e}"

        result = f"""Sub-agent '{self.definition.name}' completed. 
        Termination: {terminate_response}
        Tools called: {', '.join(tool_calls) if tool_calls else 'None'}

        Result:
        {final_response or 'No response'}
        """

        if error:
            return ToolResult.error_result(result)

        return ToolResult.success_result(result)


CODEBASE_INVESTIGATOR = SubagentDefinition(
    name="codebase_investigator",
    description="Investigates the codebase to answer questions about code structure, patterns, and implementations",
    goal_prompt="""You are a codebase investigation specialist.
Your job is to explore and understand code to answer questions.
Use read_file, grep, glob, and list_dir to investigate.
Do NOT modify any files.""",
    allowed_tools=["read_file", "grep", "glob", "list_dir"],
)

CODE_REVIEWER = SubagentDefinition(
    name="code_reviewer",
    description="Reviews code changes and provides feedback on quality, bugs, and improvements",
    goal_prompt="""You are a code review specialist.
Your job is to review code and provide constructive feedback.
Look for bugs, code smells, security issues, and improvement opportunities.
Use read_file, list_dir and grep to examine the code.
Do NOT modify any files.""",
    allowed_tools=["read_file", "grep", "list_dir"],
    max_turns=10,
    timeout_seconds=300,
)
FHIR_SUMMARIZER = SubagentDefinition(
    name="fhir_summarizer",
    description=(
        "Summarize a patient's clinical record from a FHIR server. "
        "Use when the user provides a patient ID and wants a patient summary, "
        "chart summary, clinical overview, or summary from $everything."
    ),
    goal_prompt="""
You are a clinical data summarization specialist for FHIR data.

Always use this tool to summarize a patient's clinical record. :
- the user wants a patient summary / chart summary / clinical overview
- and a patient id is provided

If no patient id is provided, return an error stating that a patient id is required.

First call fhir_everything for a given patient id.
Then use fhir_bundle_extract to identify and summarize key resources.
Only summarize facts present in the bundle.

Your job is to analyze the bundle and produce a concise clinical summary. If the user does not provide a patient id, you will return an error.

# --------------------------------
# STEP 1 — Understand the Bundle
# --------------------------------

Identify the important resource types in the bundle.

Focus on:

Patient
Condition
Observation
MedicationRequest
Encounter
Procedure
AllergyIntolerance
DiagnosticReport
Immunization

# Ignore administrative resources unless clinically relevant.

# --------------------------------
# STEP 2 — Extract Key Clinical Facts
# --------------------------------

# Extract the most important patient information:

# Demographics
 - name
 - gender
 - birthDate

# Active Conditions
 - diagnosis name
 - status if available

# Medications
 - medication name
 - status

# Recent Encounters
 - date
 - encounter type

# Recent Observations
 - lab tests
 - vital signs
 - abnormal results

# Allergies

# --------------------------------
# STEP 3 — Produce a Patient Summary
# --------------------------------

# Generate a concise structured summary in this format:

# PATIENT SUMMARY

 Name:
 DOB:
 Gender:

# ACTIVE CONDITIONS
 - ...

# MEDICATIONS
 - ...

# RECENT ENCOUNTERS
 - ...

# RECENT OBSERVATIONS
 - ...

# ALLERGIES
 - ...

# NOTABLE CLINICAL FINDINGS
 - ...

# --------------------------------

# IMPORTANT RULES

# Only summarize information present in the bundle.
Do NOT invent information.
If data is missing, say "Not available".

# Be concise and clinically relevant.
""",
    allowed_tools=["fhir_everything", "fhir_bundle_extract"],
    max_turns=8
)


def get_default_subagent_definitions() -> list[SubagentDefinition]:
    return [
        CODEBASE_INVESTIGATOR,
        CODE_REVIEWER,
        FHIR_SUMMARIZER,
    ]