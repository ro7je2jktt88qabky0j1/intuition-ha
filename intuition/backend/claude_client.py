"""
Claude API client for Intuition.
Handles all AI-powered features - log analysis, health checks, automation assistance.
"""

import os
import httpx
from typing import Optional

CLAUDE_API_KEY = os.environ.get("CLAUDE_API_KEY", "")
CLAUDE_MODEL = "claude-sonnet-4-5"
CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"


def _headers():
    return {
        "x-api-key": CLAUDE_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }


def is_configured() -> bool:
    """Check if Claude API key is set."""
    return bool(CLAUDE_API_KEY)


async def analyze_logs(log_content: str) -> dict:
    """
    Analyze HA error log and return categorized plain English report.
    Returns: {summary, errors, warnings, info, recommendations}
    """
    if not is_configured():
        return {"error": "Claude API key not configured. Add it in the add-on settings."}

    system = """You are an expert Home Assistant system analyst. You analyze HA log files and provide clear, actionable plain English reports.

Your response must be valid JSON with this exact structure:
{
  "summary": "2-3 sentence overview of system health",
  "error_count": 0,
  "warning_count": 0,
  "errors": [
    {
      "title": "Short title",
      "detail": "Plain English explanation of what this error means",
      "action": "What the user should do about it",
      "severity": "critical|high|medium"
    }
  ],
  "warnings": [
    {
      "title": "Short title", 
      "detail": "Plain English explanation",
      "action": "What to do or whether to ignore it",
      "severity": "medium|low"
    }
  ],
  "info": [
    {
      "title": "Short title",
      "detail": "What this informational entry means"
    }
  ],
  "recommendations": [
    "Specific actionable recommendation based on log patterns"
  ]
}

Rules:
- Write for a smart non-developer. No jargon without explanation.
- Group repeated errors — don't list the same error 50 times
- Distinguish between things that need fixing now vs things to monitor vs things to ignore
- Be specific about what caused each issue when possible
- Recommendations should be concrete and actionable
- Return ONLY the JSON object, no markdown, no preamble"""

    user = f"""Analyze this Home Assistant log file and return your analysis as JSON:

{log_content[-15000:]}"""

    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(
            CLAUDE_API_URL,
            headers=_headers(),
            json={
                "model": CLAUDE_MODEL,
                "max_tokens": 4000,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            },
        )
        if not r.is_success:
            error_detail = r.text
            import logging
            logging.getLogger("intuition").error(f"Claude API error {r.status_code}: {error_detail}")
            return {"error": f"Claude API error {r.status_code}: {error_detail[:200]}"}
        data = r.json()
        text = data["content"][0]["text"]

        import json
        text = text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        return json.loads(text.strip())


async def health_check(
    files: dict,
    entities: list,
    areas: list,
    logs: str,
    host_info: dict,
    core_info: dict,
) -> dict:
    """
    Full system health check across YAML, entities, logs, and hardware.
    Returns structured report.
    """
    if not is_configured():
        return {"error": "Claude API key not configured."}

    system = """You are an expert Home Assistant system health analyst. You perform comprehensive health checks and return structured JSON reports.

Return valid JSON with this structure:
{
  "overall_health": "excellent|good|fair|poor",
  "summary": "2-3 sentence overall assessment",
  "sections": [
    {
      "title": "Section name e.g. Automations, Entities, System, Logs",
      "status": "ok|warn|error",
      "items": [
        {
          "title": "Issue or finding title",
          "detail": "Plain English explanation",
          "action": "What to do, or null if no action needed",
          "severity": "info|low|medium|high|critical"
        }
      ]
    }
  ],
  "quick_wins": [
    "Simple things that can be fixed or improved right now"
  ]
}

Check for:
AUTOMATIONS/SCRIPTS:
- Entity IDs referenced that don't exist in the entity registry
- Deprecated trigger patterns (call_service event triggers for input_button)
- Missing automations_enabled checks where appropriate
- Redundant automations doing the same thing
- Non-blocking patterns (missing continue_on_error)
- Orphaned helpers (defined but never referenced)

ENTITIES/DEVICES:
- Unavailable entities
- Entities with unknown state for extended period
- Devices that may have dropped off

SYSTEM:
- Any hardware concerns from host info
- HA version status
- Memory or storage concerns

LOGS:
- Recurring errors
- Integration failures
- Anything needing immediate attention

Return ONLY the JSON object."""

    # Build context
    entity_ids = [e["entity_id"] for e in entities]
    unavailable = [e["entity_id"] for e in entities if e.get("state") in ["unavailable", "unknown"]]

    file_summary = "\n\n".join([
        f"### {name}\n{content[:3000]}{'...(truncated)' if len(content) > 3000 else ''}"
        for name, content in files.items()
        if content
    ])

    user = f"""Perform a full health check on this Home Assistant installation.

## CONFIG FILES
{file_summary}

## ENTITY SUMMARY
Total entities: {len(entities)}
Unavailable/Unknown: {len(unavailable)}
Unavailable entity IDs: {', '.join(unavailable[:30])}
All entity IDs: {', '.join(entity_ids[:200])}

## AREAS
{', '.join([a.get('name', '') for a in areas])}

## SYSTEM INFO
HA Version: {core_info.get('data', {}).get('version', 'unknown')}
Host: {host_info.get('data', {}).get('hostname', 'unknown')}
Architecture: {host_info.get('data', {}).get('chassis', 'unknown')}

## RECENT LOGS (last 5000 chars)
{logs[-5000:] if logs else 'Not available'}"""

    async with httpx.AsyncClient(timeout=90) as client:
        r = await client.post(
            CLAUDE_API_URL,
            headers=_headers(),
            json={
                "model": CLAUDE_MODEL,
                "max_tokens": 6000,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            },
        )
        if not r.is_success:
            error_detail = r.text
            import logging
            logging.getLogger("intuition").error(f"Claude API error {r.status_code}: {error_detail}")
            return {"error": f"Claude API error {r.status_code}: {error_detail[:200]}"}
        data = r.json()
        text = data["content"][0]["text"].strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]

        import json
        return json.loads(text.strip())


async def chat(
    messages: list,
    files: dict,
    entities: list,
    areas: list,
    system_prompt: str,
) -> str:
    """
    General chat for automation assistance.
    Returns the assistant's response text.
    """
    if not is_configured():
        return "Claude API key not configured. Add it in the add-on settings."

    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(
            CLAUDE_API_URL,
            headers=_headers(),
            json={
                "model": CLAUDE_MODEL,
                "max_tokens": 8000,
                "system": system_prompt,
                "messages": messages,
            },
        )
        r.raise_for_status()
        data = r.json()
        return data["content"][0]["text"]
