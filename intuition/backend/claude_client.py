"""
Claude API client for Intuition.
All AI-powered features: log analysis, health checks, automation assistance.
"""

import os
import json
import logging
import httpx

logger = logging.getLogger("intuition")

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
    return bool(CLAUDE_API_KEY)


def _parse_json_response(text: str) -> dict:
    """Parse JSON from Claude response, stripping any markdown fences."""
    text = text.strip()
    if text.startswith("```"):
        parts = text.split("```")
        if len(parts) >= 2:
            text = parts[1]
            if text.startswith("json"):
                text = text[4:]
    return json.loads(text.strip())


async def _call_claude(system: str, user: str, max_tokens: int = 4000, timeout: int = 90) -> str:
    """Make a Claude API call and return the response text."""
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(
            CLAUDE_API_URL,
            headers=_headers(),
            json={
                "model": CLAUDE_MODEL,
                "max_tokens": max_tokens,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            },
        )
        if not r.is_success:
            error_body = r.text
            try:
                error_data = json.loads(error_body)
                error_msg = error_data.get("error", {}).get("message", error_body)
            except Exception:
                error_msg = error_body[:300]
            logger.error(f"Claude API error {r.status_code}: {error_msg}")
            raise ValueError(f"Claude API error: {error_msg}")
        data = r.json()
        return data["content"][0]["text"]


async def analyze_logs(log_content: str) -> dict:
    """
    Analyze HA error log and return categorized plain English report.
    """
    if not is_configured():
        return {"error": "Claude API key not configured. Add it in the add-on Configuration tab."}

    system = """You are an expert Home Assistant system analyst. Analyze HA log files and provide clear, actionable plain English reports.

Return ONLY valid JSON with this exact structure, no markdown, no preamble:
{
  "summary": "2-3 sentence overview of system health",
  "error_count": 0,
  "warning_count": 0,
  "errors": [
    {
      "title": "Short descriptive title",
      "detail": "Plain English explanation — what this means, why it happened",
      "action": "Specific thing the user should do",
      "severity": "critical|high|medium"
    }
  ],
  "warnings": [
    {
      "title": "Short descriptive title",
      "detail": "Plain English explanation",
      "action": "What to do, or explain why it can be ignored",
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
    "Specific actionable recommendation based on patterns in these logs"
  ]
}

Rules:
- Write for a smart non-developer homeowner. No jargon without plain explanation.
- Group repeated identical errors — don't list the same error 20 times
- Distinguish: needs fixing now vs monitor vs safely ignore
- Be specific about cause when you can identify it
- Custom integrations (HACS, community) showing deprecation warnings are low priority
- Network/cloud service errors during known outages are expected — note that context
- Return ONLY the JSON object"""

    user = f"Analyze this Home Assistant log:\n\n{log_content[-15000:]}"

    try:
        text = await _call_claude(system, user, max_tokens=4000)
        return _parse_json_response(text)
    except ValueError as e:
        return {"error": str(e)}
    except Exception as e:
        logger.error(f"Log analysis error: {e}")
        return {"error": f"Analysis failed: {str(e)}"}


async def health_check(
    files: dict,
    file_metadata: dict,
    entities: list,
    areas: list,
    logs: str,
    host_info: dict,
    core_info: dict,
    integration_issues: list = None,
) -> dict:
    """
    Full system health check across YAML, entities, logs, and hardware.
    """
    if not is_configured():
        return {"error": "Claude API key not configured."}

    system = """You are an expert Home Assistant system health analyst. Perform comprehensive health checks and return structured JSON reports.

## CRITICAL CONVENTIONS — DO NOT FLAG THESE AS ISSUES

INPUT BUTTON TRIGGERS: The correct modern pattern for input_button triggers is:
  trigger: state
  entity_id: input_button.some_button
This is correct and should NOT be flagged as deprecated. The OLD deprecated pattern was call_service events. If you see state triggers on input_button entities, that is correct.

AUTOMATIONS_ENABLED CHECK ARCHITECTURE: It is a valid and intentional design pattern for some automations (especially mode_away and mode_home) to NOT check automations_enabled at the automation level when they trigger scripts that DO check automations_enabled internally. This is NOT a missing check — it is deliberate layered architecture. Do not flag this.

SPEAKER/AUDIO AUTOMATIONS: Automations that trigger audio scripts (audio_group_all, audio_ungroup_*) via input_button ARE correctly implemented even if the automation itself is simple. The logic is in the scripts. Do not flag these as orphaned or incomplete.

## WHAT TO ACTUALLY CHECK

INTEGRATION HEALTH (always check this first):
- Any integration in setup_error, setup_retry, not_loaded, or failed_unload state is a real issue
- setup_retry means it failed but is trying again — common for cloud services that went offline
- setup_error means it permanently failed — needs user attention
- Always identify what likely caused it (device powered off, cloud service down, credentials expired, etc.)
- If SmartThings or similar cloud integration fails repeatedly, distinguish between "service outage" and "your config problem"

REAL ISSUES TO FIND:
- Entity IDs referenced in YAML that do not exist in the live entity registry
- Helpers (input_boolean, input_button, timer) defined in YAML but never referenced anywhere
- Automations or scripts that reference the same device/entity for the same purpose (true redundancy)
- Device actions missing continue_on_error: true in scripts (covers, locks, media_players, fans)
- Unavailable entities that are core integrations (not mobile app sensors — those being unavailable is normal)
- Integration errors in logs that indicate real configuration problems
- Hardware concerns from system info

UNIFI PROTECT / SUPERLINK SENSORS:
- UniFi SuperLink sensors (USL-Entry, USL-Motion, etc.) paired to cameras via Protect will show some entities as unavailable
- If the Contact or Motion entity works but Humidity/Temperature/Illuminance/Moisture are unavailable, this is a known integration limitation — the Protect integration does not yet fully support all SuperLink sensor types
- Do NOT flag SuperLink environmental sensor unavailability as a problem unless the primary sensor (Contact/Motion) is also unavailable
- If a SuperLink Contact sensor is unavailable, check UniFi Protect integration connection, not batteries

LOW PRIORITY / INFORMATIONAL ONLY:
- Mobile app sensors unavailable (normal when phones are locked/offline)
- Custom integrations (HACS, community integrations) — just note they exist
- Temporary network errors if there was a known outage

Return ONLY valid JSON with this structure:
{
  "overall_health": "excellent|good|fair|poor",
  "summary": "2-3 sentence honest assessment",
  "sections": [
    {
      "title": "Section name",
      "status": "ok|warn|error",
      "items": [
        {
          "title": "Issue title",
          "detail": "Plain English explanation",
          "action": "What to do, or null",
          "severity": "info|low|medium|high|critical"
        }
      ]
    }
  ],
  "quick_wins": ["Simple actionable improvement"]
}"""

    # Build file summary for the prompt
    file_summaries = []
    for filename, info in files.items():
        key = file_metadata.get(filename, {}).get("key", "unknown")
        lines = len(info.split("\n")) if info else 0
        # Truncate large files for the prompt
        content_preview = info[:4000] + f"\n... ({lines} lines total)" if len(info) > 4000 else info
        file_summaries.append(f"### {filename} ({key}, {lines} lines)\n```yaml\n{content_preview}\n```")

    file_context = "\n\n".join(file_summaries)

    # Build integration issues text
    if integration_issues:
        issue_lines = []
        for issue in integration_issues:
            state = issue.get("state", "")
            state_desc = {
                "setup_error": "FAILED (not retrying)",
                "setup_retry": "FAILING (retrying automatically)",
                "not_loaded": "NOT LOADED",
                "failed_unload": "ERROR during unload",
                "migration_error": "MIGRATION ERROR",
            }.get(state, state)
            issue_lines.append(f"- {issue['title']} ({issue['domain']}): {state_desc}")
        integration_issues_text = "The following integrations have problems:\n" + "\n".join(issue_lines)
    else:
        integration_issues_text = "All integrations loaded successfully."

    entity_ids = [e["entity_id"] for e in entities]
    unavailable = [e["entity_id"] for e in entities if e.get("state") in ["unavailable", "unknown"]]
    # Filter out mobile app sensors from unavailable count for display
    core_unavailable = [e for e in unavailable if not any(
        x in e for x in ["iphone", "ipad", "android", "_phone", "mobile_app"]
    )]

    user = f"""Perform a full health check on this Home Assistant installation.

## CONFIG FILES ({len(files)} files discovered)
{file_context}

## LIVE ENTITY REGISTRY
Total entities: {len(entities)}
Total unavailable/unknown: {len(unavailable)} (note: mobile app sensor unavailability is normal)
Non-mobile unavailable: {', '.join(core_unavailable[:20])}
All entity IDs (first 300): {', '.join(entity_ids[:300])}

## AREAS
{', '.join([a.get('name', '') for a in areas]) or 'None configured'}

## INTEGRATION HEALTH (from config entries API)
{integration_issues_text}

## SYSTEM INFO
HA Version: {core_info.get('data', {}).get('version', 'unknown')}
Hostname: {host_info.get('data', {}).get('hostname', 'unknown')}

## RECENT LOGS (last 4000 chars)
{logs[-4000:] if logs else 'Not available'}"""

    try:
        text = await _call_claude(system, user, max_tokens=6000, timeout=120)
        return _parse_json_response(text)
    except ValueError as e:
        return {"error": str(e)}
    except Exception as e:
        logger.error(f"Health check error: {e}")
        return {"error": f"Health check failed: {str(e)}"}


async def chat(messages: list, system_prompt: str) -> str:
    """General chat for automation assistance."""
    if not is_configured():
        return "Claude API key not configured. Add it in the add-on Configuration tab."
    try:
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
            if not r.is_success:
                error_data = r.json()
                return f"Error: {error_data.get('error', {}).get('message', 'Unknown error')}"
            data = r.json()
            return data["content"][0]["text"]
    except Exception as e:
        return f"Error: {str(e)}"


async def health_ai(findings: dict) -> dict:
    """
    AI health analysis with web search for real update release notes.
    Uses Claude's web search tool to look up actual changelogs.
    """
    if not is_configured():
        return {"error": "Claude API key not configured."}

    system = """You are an expert Home Assistant system analyst. You receive structured health scan findings and provide an honest, clear assessment.

## KNOWN CONTEXT — DO NOT FLAG THESE
- Mobile app sensors being unavailable is normal when phones are locked or offline
- UniFi SuperLink environmental sensors (humidity/temperature/moisture) showing unavailable is a known integration limitation — not a problem
- Input button state triggers are correct modern HA pattern
- setup_retry on printer integrations usually means the printer is powered off

## UPDATE ASSESSMENT — HONESTY RULES
You do NOT have access to the actual release notes. Be transparent about this.

## HOME ASSISTANT VERSIONING — IMPORTANT CONTEXT
Home Assistant uses a year.month.patch format (e.g. 2026.4.1):
- PATCH release (2026.4.1 → 2026.4.2): Bug fixes only within the same month. Very low risk to apply, very low risk to skip. Apply at any convenient time.
- MONTHLY release (2026.4.x → 2026.5.x): Full monthly release with new features, deprecations, and occasionally breaking changes. These are significant releases. Users should review the official release notes at home-assistant.io/blog before applying. Low-medium risk to apply, low risk to skip short-term.
- Never describe a monthly release as "routine" or "minor" — it is a significant release even if the version increment looks small.

Rules:
- Always set notes_available to false
- For what_changed: state only what can be honestly inferred from the version pattern. Do NOT invent specifics.
- For urgency: patch → when_convenient, monthly → soon (recommend reviewing release notes first), security known → asap
- Never use phrases like "likely includes", "probably contains", or "may have" — state what you know and what you don't

## YOUR JOB
You MUST address ALL of the following:
1. Any integration_issues — explain what each means and likely cause
2. Any pending_updates — assess each honestly based on version pattern only
3. Log errors — summarize and group related ones
4. Overall system health

Return ONLY this JSON structure with no markdown, no preamble:
{
  "overall": "excellent|good|fair|poor",
  "summary": "2-3 sentences. Focus on what matters — key issues, what is working well, and overall confidence in the system. Do NOT mention entity counts.",
  "priority_items": [
    {
      "title": "Short title",
      "detail": "Plain English explanation of the issue and likely cause",
      "action": "Specific actionable thing to do",
      "severity": "high|medium|low"
    }
  ],
  "updates": [
    {
      "name": "Component name",
      "current": "current version",
      "latest": "latest version",
      "urgency": "asap|soon|when_convenient|optional",
      "urgency_reason": "One honest sentence — e.g. patch release, low urgency or security fix known in this version range",
      "what_changed": "Honest statement of what can be inferred from version pattern only. Do not guess specifics.",
      "notes_available": false,
      "apply_risk": "very_low|low|medium|high",
      "apply_risk_detail": "One sentence — patch releases are very low risk, minor releases are low-medium risk",
      "skip_risk": "none|low|medium|high",
      "skip_risk_detail": "One sentence — low for routine updates, higher if security related"
    }
  ],
  "positive_notes": [
    "Things working well worth noting"
  ],
  "log_recommendation": null
}

Urgency rules:
- asap: known security vulnerability in this version
- soon: known critical bug in this version
- when_convenient: patch or minor release, no known urgent issues
- optional: very minor or cosmetic

Return ONLY the JSON object."""

    import json
    user = f"Analyze these Home Assistant health scan findings:\n\n{json.dumps(findings, indent=2)}"

    try:
        text = await _call_claude(system, user, max_tokens=3000, timeout=120)
        return _parse_json_response(text)
    except ValueError as e:
        return {"error": str(e)}
    except Exception as e:
        logger.error(f"Health AI error: {e}")
        return {"error": f"Analysis failed: {str(e)}"}
