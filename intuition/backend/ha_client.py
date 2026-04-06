"""
Home Assistant API client for Intuition.
Uses both direct filesystem access and Supervisor API.
"""

import os
import httpx
from typing import Optional
from pathlib import Path

HA_URL = os.environ.get("HA_URL", "http://supervisor/core")
SUPERVISOR_URL = os.environ.get("SUPERVISOR_URL", "http://supervisor")
HA_TOKEN = os.environ.get("HA_TOKEN", "")

# Direct config path - available inside the add-on container
CONFIG_PATH = Path("/config")

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
    """Device registry not available via REST API."""
    return []


async def get_area_registry() -> list:
    """Get areas — gracefully returns empty if unavailable."""
    return []


async def read_config_file(filename: str) -> Optional[str]:
    """
    Read config file directly from filesystem.
    Add-ons have /config mounted as the HA config directory.
    """
    try:
        file_path = CONFIG_PATH / filename
        if file_path.exists():
            return file_path.read_text(encoding="utf-8")
    except Exception as e:
        import logging
        logging.getLogger("intuition").warning(f"Could not read {filename} from filesystem: {e}")
    return None


async def write_config_file(filename: str, content: str) -> bool:
    """Write config file directly to filesystem."""
    try:
        file_path = CONFIG_PATH / filename
        file_path.write_text(content, encoding="utf-8")
        return True
    except Exception as e:
        import logging
        logging.getLogger("intuition").error(f"Could not write {filename}: {e}")
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
    """Fetch logs via Supervisor."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
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
