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

PROBLEM_STATES = {"setup_error", "setup_retry", "failed_unload", "migration_error"}


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
    entries = await get_config_entries()
    issues = []
    for entry in entries:
        state = entry.get("state", "")
        disabled_by = entry.get("disabled_by")
        if state in ("setup_error", "setup_retry", "failed_unload", "migration_error"):
            if disabled_by in ("user", "config_entry"):
                continue
            issues.append({
                "title": entry.get("title", entry.get("domain", "Unknown")),
                "domain": entry.get("domain", ""),
                "state": state,
                "entry_id": entry.get("entry_id", ""),
                "reason": entry.get("reason", ""),
            })
        elif state == "not_loaded":
            if disabled_by and disabled_by not in ("user", "config_entry"):
                issues.append({
                    "title": entry.get("title", entry.get("domain", "Unknown")),
                    "domain": entry.get("domain", ""),
                    "state": state,
                    "entry_id": entry.get("entry_id", ""),
                    "reason": entry.get("reason", ""),
                    "disabled_by": disabled_by,
                })
    return issues


async def get_update_info() -> dict:
    """
    Get update availability for core, OS, supervisor, and add-ons.
    Returns structured update summary.
    """
    updates = []

    # Core
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{SUPERVISOR_URL}/core/info", headers=_ha_headers())
            if r.status_code == 200:
                d = r.json().get("data", {})
                if d.get("update_available"):
                    updates.append({
                        "name": "Home Assistant Core",
                        "current": d.get("version", ""),
                        "latest": d.get("version_latest", ""),
                        "type": "core",
                    })
    except Exception as e:
        logger.warning(f"Could not fetch core info: {e}")

    # OS
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{SUPERVISOR_URL}/os/info", headers=_ha_headers())
            if r.status_code == 200:
                d = r.json().get("data", {})
                if d.get("update_available"):
                    updates.append({
                        "name": "Home Assistant OS",
                        "current": d.get("version", ""),
                        "latest": d.get("version_latest", ""),
                        "type": "os",
                    })
    except Exception as e:
        logger.warning(f"Could not fetch OS info: {e}")

    # Supervisor
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{SUPERVISOR_URL}/supervisor/info", headers=_ha_headers())
            if r.status_code == 200:
                d = r.json().get("data", {})
                if d.get("update_available"):
                    updates.append({
                        "name": "Supervisor",
                        "current": d.get("version", ""),
                        "latest": d.get("version_latest", ""),
                        "type": "supervisor",
                    })
    except Exception as e:
        logger.warning(f"Could not fetch supervisor info: {e}")

    # Add-ons
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{SUPERVISOR_URL}/addons", headers=_ha_headers())
            if r.status_code == 200:
                addons = r.json().get("data", {}).get("addons", [])
                for addon in addons:
                    if addon.get("update_available"):
                        updates.append({
                            "name": addon.get("name", addon.get("slug", "")),
                            "current": addon.get("version", ""),
                            "latest": addon.get("version_latest", ""),
                            "type": "addon",
                            "slug": addon.get("slug", ""),
                        })
    except Exception as e:
        logger.warning(f"Could not fetch addon info: {e}")

    return {
        "updates": updates,
        "count": len(updates),
        "has_updates": len(updates) > 0,
        "core_update": next((u for u in updates if u["type"] == "core"), None),
    }


async def get_backup_info() -> dict:
    """
    Get latest backup info from Supervisor.
    Returns last backup date, success status, and age in hours.
    """
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(f"{SUPERVISOR_URL}/backups", headers=_ha_headers())
            if r.status_code == 200:
                data = r.json().get("data", {})
                backups = data.get("backups", [])
                if not backups:
                    return {"has_backup": False, "last_backup": None, "age_hours": None}

                # Sort by date descending, get most recent
                sorted_backups = sorted(
                    backups,
                    key=lambda b: b.get("date", ""),
                    reverse=True
                )
                latest = sorted_backups[0]

                from datetime import datetime, timezone
                date_str = latest.get("date", "")
                backup_dt = None
                age_hours = None

                if date_str:
                    try:
                        # Handle ISO format with timezone
                        backup_dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                        now = datetime.now(timezone.utc)
                        age_hours = (now - backup_dt).total_seconds() / 3600
                    except Exception:
                        pass

                return {
                    "has_backup": True,
                    "last_backup": date_str,
                    "last_backup_name": latest.get("name", ""),
                    "last_backup_type": latest.get("type", ""),
                    "last_backup_size": latest.get("size", 0),
                    "age_hours": age_hours,
                    "total_backups": len(backups),
                    "backup_dt": backup_dt.isoformat() if backup_dt else None,
                }
    except Exception as e:
        logger.warning(f"Could not fetch backup info: {e}")
    return {"has_backup": False, "last_backup": None, "age_hours": None}


async def get_system_resources() -> dict:
    """
    Get host system resources: CPU, memory, disk.
    Uses host/info for disk and core/stats for CPU/memory.
    """
    resources = {
        "cpu_percent": None,
        "memory_percent": None,
        "disk_used_gb": None,
        "disk_total_gb": None,
        "disk_percent": None,
    }

    # CPU and memory from core stats
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{SUPERVISOR_URL}/core/stats", headers=_ha_headers())
            if r.status_code == 200:
                d = r.json().get("data", {})
                resources["cpu_percent"] = round(d.get("cpu_percent", 0), 1)
                mem_usage = d.get("memory_usage", 0)
                mem_limit = d.get("memory_limit", 1)
                if mem_limit > 0:
                    resources["memory_percent"] = round((mem_usage / mem_limit) * 100, 1)
    except Exception as e:
        logger.warning(f"Could not fetch core stats: {e}")

    # Disk from host info
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{SUPERVISOR_URL}/host/info", headers=_ha_headers())
            if r.status_code == 200:
                d = r.json().get("data", {})
                disk_free = d.get("disk_free", 0)   # GB
                disk_total = d.get("disk_total", 0)  # GB
                disk_used = d.get("disk_used", 0)    # GB
                if disk_total > 0:
                    resources["disk_used_gb"] = round(disk_used, 1)
                    resources["disk_total_gb"] = round(disk_total, 1)
                    resources["disk_percent"] = round((disk_used / disk_total) * 100, 1)
    except Exception as e:
        logger.warning(f"Could not fetch host info for disk: {e}")

    return resources


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
        file_summary[filename] = {
            "type": info["type"], "key": key,
            "lines": info["lines"], "entity_refs": len(refs),
        }

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
