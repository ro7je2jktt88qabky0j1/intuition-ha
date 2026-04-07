"""
Home Assistant API client for Intuition.
Handles all HA data access including dynamic config file discovery.
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

# Files to never read regardless of what we find
EXCLUDED_FILES = {
    "secrets.yaml",
    "known_devices.yaml",
    ".gitignore",
}

# Directories to never scan
EXCLUDED_DIRS = {
    ".storage",
    ".cloud",
    ".HA_VERSION",
    "custom_components",
    "www",
    "themes",
    "deps",
    "tts",
    "backups",
    ".git",
}

# YAML keys in configuration.yaml that are relevant to automation logic
RELEVANT_KEYS = {
    "automation", "script", "scene", "group",
    "input_boolean", "input_number", "input_select",
    "input_text", "input_datetime", "input_button",
    "timer", "counter", "schedule",
    "switch", "sensor", "binary_sensor",
    "template", "homeassistant", "http",
    "notify", "alert", "variable",
    "packages",
}


def _ha_headers():
    return {
        "Authorization": f"Bearer {HA_TOKEN}",
        "Content-Type": "application/json",
    }


# ── HA API calls ──────────────────────────────────────────────────────────────

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
    """Read a file safely, returning None on any error."""
    try:
        if path.exists() and path.is_file():
            return path.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning(f"Could not read {path}: {e}")
    return None


def _parse_includes(content: str, base_path: Path) -> list[dict]:
    """
    Parse !include and !include_dir_* directives from a YAML file.
    Returns list of {path, type, key} dicts.
    """
    results = []

    # Match: key: !include filename.yaml
    include_pattern = re.compile(
        r'^(\s*)(\w+)\s*:\s*!include\s+(.+\.ya?ml)\s*$',
        re.MULTILINE
    )
    for match in include_pattern.finditer(content):
        key = match.group(2).lower()
        filename = match.group(3).strip()
        full_path = base_path / filename
        results.append({
            "path": full_path,
            "key": key,
            "type": "include",
            "pattern": "single",
        })

    # Match: key: !include_dir_merge_list dirname
    # Match: key: !include_dir_merge_named dirname
    # Match: key: !include_dir_list dirname
    # Match: key: !include_dir_named dirname
    dir_include_pattern = re.compile(
        r'^(\s*)(\w+)\s*:\s*!(include_dir_\w+)\s+(.+)\s*$',
        re.MULTILINE
    )
    for match in dir_include_pattern.finditer(content):
        key = match.group(2).lower()
        directive = match.group(3)
        dirname = match.group(4).strip()
        dir_path = base_path / dirname
        results.append({
            "path": dir_path,
            "key": key,
            "type": "include_dir",
            "pattern": directive,
        })

    return results


def _collect_yaml_from_dir(dir_path: Path) -> list[Path]:
    """Collect all YAML files from a directory recursively."""
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
    """
    Dynamically discover all relevant config files by:
    1. Reading configuration.yaml
    2. Following all !include directives
    3. Building a complete map of active config files

    Returns dict of {relative_path: {content, key, type, lines}}
    """
    discovered = {}

    # Always start with configuration.yaml
    config_yaml_path = CONFIG_PATH / "configuration.yaml"
    config_content = _read_file_safe(config_yaml_path)
    if not config_content:
        logger.error("Could not read configuration.yaml - is /config mounted?")
        return discovered

    discovered["configuration.yaml"] = {
        "content": config_content,
        "key": "root",
        "type": "root",
        "lines": len(config_content.split("\n")),
        "path": str(config_yaml_path),
    }

    # Parse includes from configuration.yaml
    includes = _parse_includes(config_content, CONFIG_PATH)

    for inc in includes:
        key = inc["key"]

        # Skip non-relevant keys
        if key not in RELEVANT_KEYS:
            continue

        if inc["type"] == "include":
            # Single file include
            file_path = inc["path"]
            if file_path.name in EXCLUDED_FILES:
                continue
            content = _read_file_safe(file_path)
            if content:
                rel_path = str(file_path.relative_to(CONFIG_PATH))
                discovered[rel_path] = {
                    "content": content,
                    "key": key,
                    "type": "include",
                    "lines": len(content.split("\n")),
                    "path": str(file_path),
                }
                # Check for nested includes (e.g. packages)
                nested = _parse_includes(content, file_path.parent)
                for ninc in nested:
                    if ninc["type"] == "include":
                        ncontent = _read_file_safe(ninc["path"])
                        if ncontent and ninc["path"].name not in EXCLUDED_FILES:
                            nrel = str(ninc["path"].relative_to(CONFIG_PATH))
                            discovered[nrel] = {
                                "content": ncontent,
                                "key": ninc["key"],
                                "type": "nested_include",
                                "lines": len(ncontent.split("\n")),
                                "path": str(ninc["path"]),
                            }

        elif inc["type"] == "include_dir":
            # Directory include - collect all YAML files in the directory
            dir_path = inc["path"]
            yaml_files = _collect_yaml_from_dir(dir_path)
            for file_path in yaml_files:
                if file_path.name in EXCLUDED_FILES:
                    continue
                content = _read_file_safe(file_path)
                if content:
                    try:
                        rel_path = str(file_path.relative_to(CONFIG_PATH))
                        discovered[rel_path] = {
                            "content": content,
                            "key": key,
                            "type": "include_dir",
                            "lines": len(content.split("\n")),
                            "path": str(file_path),
                            "dir_pattern": inc["pattern"],
                        }
                    except ValueError:
                        pass

    # Also check for packages directory explicitly
    packages_dir = CONFIG_PATH / "packages"
    if packages_dir.exists() and packages_dir.is_dir():
        for file_path in _collect_yaml_from_dir(packages_dir):
            rel_path = str(file_path.relative_to(CONFIG_PATH))
            if rel_path not in discovered:
                content = _read_file_safe(file_path)
                if content:
                    discovered[rel_path] = {
                        "content": content,
                        "key": "package",
                        "type": "package",
                        "lines": len(content.split("\n")),
                        "path": str(file_path),
                    }

    logger.info(f"Discovered {len(discovered)} config files")
    return discovered


def build_dependency_map(config_files: dict) -> dict:
    """
    Build a cross-reference map of the entire config.
    Returns {
        entity_ids_defined: [...],
        entity_ids_referenced: [...],
        script_calls: {automation_id: [script_id, ...]},
        helper_usage: {helper_id: [files_referencing_it]},
        orphaned_helpers: [...],
        file_summary: {filename: {type, key, entity_count}},
    }
    """
    entity_pattern = re.compile(r'\b([a-z_]+\.[a-z0-9_]+)\b')
    script_call_pattern = re.compile(r'script\.[a-z0-9_]+')
    input_bool_def_pattern = re.compile(r'^([a-z][a-z0-9_]*):\s*$', re.MULTILINE)

    all_entity_refs = set()
    defined_helpers = {}  # entity_id -> filename
    file_summary = {}

    for filename, info in config_files.items():
        content = info["content"]
        key = info["key"]
        refs = set(entity_pattern.findall(content))
        all_entity_refs.update(refs)

        # Track helper definitions
        if key in ("input_boolean", "input_button", "timer", "counter",
                   "input_number", "input_select", "input_text", "input_datetime"):
            for match in input_bool_def_pattern.finditer(content):
                helper_id = f"{key}.{match.group(1)}"
                defined_helpers[helper_id] = filename

        file_summary[filename] = {
            "type": info["type"],
            "key": key,
            "lines": info["lines"],
            "entity_refs": len(refs),
        }

    return {
        "entity_ids_referenced": sorted(list(all_entity_refs)),
        "defined_helpers": defined_helpers,
        "file_summary": file_summary,
        "total_files": len(config_files),
    }


# ── File write ────────────────────────────────────────────────────────────────

async def write_config_file(filename: str, content: str) -> bool:
    """Write a config file directly to the filesystem."""
    try:
        file_path = CONFIG_PATH / filename
        # Safety check — only write files within /config
        file_path.resolve().relative_to(CONFIG_PATH.resolve())
        file_path.write_text(content, encoding="utf-8")
        return True
    except Exception as e:
        logger.error(f"Could not write {filename}: {e}")
        return False


# Keep this for backward compatibility with any code that calls it directly
CONFIG_FILES = [
    "automations.yaml",
    "scripts.yaml",
    "input_booleans.yaml",
    "input_button.yaml",
    "timers.yaml",
    "configuration.yaml",
]


async def read_config_file(filename: str) -> Optional[str]:
    return _read_file_safe(CONFIG_PATH / filename)


async def read_all_config_files() -> dict:
    """Legacy method — now returns discovered files content only."""
    discovered = discover_config_files()
    return {k: v["content"] for k, v in discovered.items()}
