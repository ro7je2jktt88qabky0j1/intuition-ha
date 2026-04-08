"""
Home Assistant API client for Intuition.
Handles all HA data access including dynamic config file discovery
and integration health monitoring via config entries.
"""

import os
import re
import logging
import httpx
from pathlib import Path
from typing import Optional

logger = logging.getLogger("intuition")

HA_URL = os.environ.get("HA_URL", "http://supervisor/core")
SUPERVISOR_URL = os.environ.get("SUPERVISOR_URL", "http://supervisor")
HA_TOKEN = os.environ.get("HA_TOKEN", "")
CONFIG_PATH = Path("/config")

EXCLUDED_FILES = {"secrets.yaml", "known_devices.yaml", ".gitignore"}
EXCLUDED_DIRS = {".storage", ".cloud", "custom_components", "www", "themes", "deps", "tts", "backups", ".git"}
RELEVANT_KEYS = {
    "automation", "script", "scene", "group",
    "input_boolean", "input_number", "input_select",
    "input_text", "input_datetime", "input_button",
    "timer", "counter", "schedule",
    "switch", "sensor", "binary_sensor",
    "template", "homeassistant", "http",
    "notify", "alert", "variable", "packages",
}

# Integration states that indicate problems
PROBLEM_STATES = {"setup_error", "setup_retry", "not_loaded", "failed_unload", "migration_error"}


def _ha_headers():
    return {"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"}


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
    return []


async def get_area_registry() -> list:
    return []


async def get_config_entries() -> list:
    """
    Get all integration config entries with their current state.
    Used to detect broken/failing integrations (printer off, cloud service down, etc).

    Entry states:
    - loaded: working normally
    - setup_error: failed to set up, not retrying
    - setup_retry: failed but will retry automatically
    - not_loaded: not loaded (disabled or dependency missing)
    - failed_unload: error during unload
    - migration_error: config migration failed
    """
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                f"{HA_URL}/api/config/config_entries/entry",
                headers=_ha_headers(),
            )
            if r.status_code == 200:
                return r.json()
    except Exception as e:
        logger.warning(f"Could not fetch config entries: {e}")
    return []


async def get_integration_issues() -> list:
    """
    Return only config entries that have problems.
    Filters out disabled entries (intentionally not_loaded).
    """
    entries = await get_config_entries()
    issues = []
    for entry in entries:
        state = entry.get("state", "")
        disabled_by = entry.get("disabled_by")
        # Skip intentionally disabled integrations
        if disabled_by:
            continue
        if state in PROBLEM_STATES:
            issues.append({
                "title": entry.get("title", entry.get("domain", "Unknown")),
                "domain": entry.get("domain", ""),
                "state": state,
                "entry_id": entry.get("entry_id", ""),
                "reason": entry.get("reason", ""),
            })
    return issues


async def run_config_check() -> dict:
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                f"{HA_URL}/api/config/core/check_config",
                headers=_ha_headers(), json={},
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
                headers=_ha_headers(), json={},
            )
            return r.status_code == 200
    except Exception:
        return False


async def get_error_log() -> str:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(f"{SUPERVISOR_URL}/core/logs", headers=_ha_headers())
            if r.status_code == 200:
                return r.text
    except Exception:
        pass
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(f"{HA_URL}/api/error_log", headers=_ha_headers())
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


# ── Dynamic file discovery ────────────────────────────────────────────────────

def _read_file_safe(path: Path) -> Optional[str]:
    try:
        if path.exists() and path.is_file():
            return path.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning(f"Could not read {path}: {e}")
    return None


def _parse_includes(content: str, base_path: Path) -> list:
    results = []
    include_pattern = re.compile(r'^(\s*)(\w+)\s*:\s*!include\s+(.+\.ya?ml)\s*$', re.MULTILINE)
    for match in include_pattern.finditer(content):
        results.append({
            "path": base_path / match.group(3).strip(),
            "key": match.group(2).lower(),
            "type": "include", "pattern": "single",
        })
    dir_pattern = re.compile(r'^(\s*)(\w+)\s*:\s*!(include_dir_\w+)\s+(.+)\s*$', re.MULTILINE)
    for match in dir_pattern.finditer(content):
        results.append({
            "path": base_path / match.group(4).strip(),
            "key": match.group(2).lower(),
            "type": "include_dir", "pattern": match.group(3),
        })
    return results


def _collect_yaml_from_dir(dir_path: Path) -> list:
    files = []
    if not dir_path.exists() or not dir_path.is_dir():
        return files
    for f in sorted(dir_path.rglob("*.yaml")):
        if f.name not in EXCLUDED_FILES and f.parent.name not in EXCLUDED_DIRS:
            files.append(f)
    for f in sorted(dir_path.rglob("*.yml")):
        if f.name not in EXCLUDED_FILES and f.parent.name not in EXCLUDED_DIRS:
            files.append(f)
    return files


def discover_config_files() -> dict:
    discovered = {}
    config_yaml_path = CONFIG_PATH / "configuration.yaml"
    config_content = _read_file_safe(config_yaml_path)
    if not config_content:
        logger.error("Could not read configuration.yaml")
        return discovered

    discovered["configuration.yaml"] = {
        "content": config_content, "key": "root", "type": "root",
        "lines": len(config_content.split("\n")), "path": str(config_yaml_path),
    }

    for inc in _parse_includes(config_content, CONFIG_PATH):
        key = inc["key"]
        if key not in RELEVANT_KEYS:
            continue
        if inc["type"] == "include":
            fp = inc["path"]
            if fp.name in EXCLUDED_FILES:
                continue
            content = _read_file_safe(fp)
            if content:
                rel = str(fp.relative_to(CONFIG_PATH))
                discovered[rel] = {
                    "content": content, "key": key, "type": "include",
                    "lines": len(content.split("\n")), "path": str(fp),
                }
                for ninc in _parse_includes(content, fp.parent):
                    if ninc["type"] == "include":
                        nc = _read_file_safe(ninc["path"])
                        if nc and ninc["path"].name not in EXCLUDED_FILES:
                            try:
                                nrel = str(ninc["path"].relative_to(CONFIG_PATH))
                                discovered[nrel] = {
                                    "content": nc, "key": ninc["key"], "type": "nested_include",
                                    "lines": len(nc.split("\n")), "path": str(ninc["path"]),
                                }
                            except ValueError:
                                pass
        elif inc["type"] == "include_dir":
            for fp in _collect_yaml_from_dir(inc["path"]):
                if fp.name in EXCLUDED_FILES:
                    continue
                content = _read_file_safe(fp)
                if content:
                    try:
                        rel = str(fp.relative_to(CONFIG_PATH))
                        discovered[rel] = {
                            "content": content, "key": key, "type": "include_dir",
                            "lines": len(content.split("\n")), "path": str(fp),
                            "dir_pattern": inc["pattern"],
                        }
                    except ValueError:
                        pass

    packages_dir = CONFIG_PATH / "packages"
    if packages_dir.exists():
        for fp in _collect_yaml_from_dir(packages_dir):
            rel = str(fp.relative_to(CONFIG_PATH))
            if rel not in discovered:
                content = _read_file_safe(fp)
                if content:
                    discovered[rel] = {
                        "content": content, "key": "package", "type": "package",
                        "lines": len(content.split("\n")), "path": str(fp),
                    }

    logger.info(f"Discovered {len(discovered)} config files")
    return discovered


def build_dependency_map(config_files: dict) -> dict:
    entity_pattern = re.compile(r'\b([a-z_]+\.[a-z0-9_]+)\b')
    input_def_pattern = re.compile(r'^([a-z][a-z0-9_]*):\s*$', re.MULTILINE)
    all_refs = set()
    defined_helpers = {}
    file_summary = {}

    for filename, info in config_files.items():
        content = info["content"]
        key = info["key"]
        refs = set(entity_pattern.findall(content))
        all_refs.update(refs)
        if key in ("input_boolean", "input_button", "timer", "counter",
                   "input_number", "input_select", "input_text", "input_datetime"):
            for match in input_def_pattern.finditer(content):
                defined_helpers[f"{key}.{match.group(1)}"] = filename
        file_summary[filename] = {"type": info["type"], "key": key, "lines": info["lines"], "entity_refs": len(refs)}

    return {
        "entity_ids_referenced": sorted(list(all_refs)),
        "defined_helpers": defined_helpers,
        "file_summary": file_summary,
        "total_files": len(config_files),
    }


async def write_config_file(filename: str, content: str) -> bool:
    try:
        file_path = CONFIG_PATH / filename
        file_path.resolve().relative_to(CONFIG_PATH.resolve())
        file_path.write_text(content, encoding="utf-8")
        return True
    except Exception as e:
        logger.error(f"Could not write {filename}: {e}")
        return False


CONFIG_FILES = [
    "automations.yaml", "scripts.yaml", "input_booleans.yaml",
    "input_button.yaml", "timers.yaml", "configuration.yaml",
]


async def read_config_file(filename: str) -> Optional[str]:
    return _read_file_safe(CONFIG_PATH / filename)


async def read_all_config_files() -> dict:
    discovered = discover_config_files()
    return {k: v["content"] for k, v in discovered.items()}
