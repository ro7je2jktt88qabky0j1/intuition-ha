"""
Home Assistant API client for Intuition.
Uses Supervisor token for elevated file access - no user token needed.
"""

import os
import httpx
from typing import Optional

HA_URL = os.environ.get("HA_URL", "http://supervisor/core")
SUPERVISOR_URL = os.environ.get("SUPERVISOR_URL", "http://supervisor")
HA_TOKEN = os.environ.get("HA_TOKEN", "")

CONFIG_FILES = [
    "automations.yaml",
    "scripts.yaml",
    "input_booleans.yaml",
    "input_button.yaml",
    "timers.yaml",
    "configuration.yaml",
]


def _ha_headers():
    return {
        "Authorization": f"Bearer {HA_TOKEN}",
        "Content-Type": "application/json",
    }


async def get_ha_info() -> dict:
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(f"{HA_URL}/api/", headers=_ha_headers())
        r.raise_for_status()
        return r.json()


async def get_states() -> list:
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(f"{HA_URL}/api/states", headers=_ha_headers())
        r.raise_for_status()
        return r.json()


async def get_device_registry() -> list:
    """Device registry not available via REST API — returns empty list."""
    return []


async def get_area_registry() -> list:
    """Get all areas via Supervisor core API."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                f"{HA_URL}/api/config/area_registry/list",
                headers=_ha_headers(),
                json={},
            )
            if r.status_code == 200:
                data = r.json()
                return data.get("result", [])
    except Exception:
        pass
    return []


async def read_config_file(filename: str) -> Optional[str]:
    """Read a config file via Supervisor file manager API."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                f"{SUPERVISOR_URL}/files/config/{filename}",
                headers=_ha_headers(),
            )
            if r.status_code == 200:
                return r.text
    except Exception:
        pass
    return None


async def write_config_file(filename: str, content: str) -> bool:
    """Write a config file via Supervisor file manager."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                f"{SUPERVISOR_URL}/files/config/{filename}",
                headers={
                    "Authorization": f"Bearer {HA_TOKEN}",
                    "Content-Type": "application/octet-stream",
                },
                content=content.encode("utf-8"),
            )
            return r.status_code == 200
    except Exception:
        return False


async def read_all_config_files() -> dict:
    files = {}
    for filename in CONFIG_FILES:
        content = await read_config_file(filename)
        if content:
            files[filename] = content
    return files


async def run_config_check() -> dict:
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                f"{HA_URL}/api/config/core/check_config",
                headers=_ha_headers(),
                json={},
            )
            r.raise_for_status()
            data = r.json()
            return {"passed": data.get("result") == "valid", "errors": data.get("errors", "")}
    except Exception as e:
        return {"passed": False, "errors": str(e)}


async def reload_domain(domain: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                f"{HA_URL}/api/services/{domain}/reload",
                headers=_ha_headers(),
                json={},
            )
            return r.status_code == 200
    except Exception:
        return False


async def get_error_log() -> str:
    """Fetch the HA error log via Supervisor."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            # Try Supervisor logging endpoint
            r = await client.get(
                f"{SUPERVISOR_URL}/core/logs",
                headers=_ha_headers(),
            )
            if r.status_code == 200:
                return r.text
    except Exception:
        pass
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            # Fallback to HA REST API error log
            r = await client.get(
                f"{HA_URL}/api/error_log",
                headers=_ha_headers(),
            )
            if r.status_code == 200:
                return r.text
    except Exception:
        pass
    return ""


async def get_entity_history(entity_id: str, days: int = 7) -> list:
    try:
        from datetime import datetime, timedelta
        start = (datetime.utcnow() - timedelta(days=days)).isoformat()
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(
                f"{HA_URL}/api/history/period/{start}",
                headers=_ha_headers(),
                params={"filter_entity_id": entity_id},
            )
            r.raise_for_status()
            return r.json()
    except Exception:
        return []


async def get_supervisor_info() -> dict:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{SUPERVISOR_URL}/info", headers=_ha_headers())
            if r.status_code == 200:
                return r.json()
    except Exception:
        pass
    return {}


async def get_core_info() -> dict:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{SUPERVISOR_URL}/core/info", headers=_ha_headers())
            if r.status_code == 200:
                return r.json()
    except Exception:
        pass
    return {}


async def get_host_info() -> dict:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{SUPERVISOR_URL}/host/info", headers=_ha_headers())
            if r.status_code == 200:
                return r.json()
    except Exception:
        pass
    return {}
