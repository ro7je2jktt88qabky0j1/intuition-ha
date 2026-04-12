"""
Intuition - Your home just knows.
FastAPI backend with HA ingress support and dynamic config discovery.
"""

import os
import re
import logging
from pathlib import Path
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional, List

import ha_client
import claude_client

log_level = os.environ.get("LOG_LEVEL", "info").upper()
logging.basicConfig(level=getattr(logging, log_level, logging.INFO))
logger = logging.getLogger("intuition")

ingress_entry = os.environ.get("INGRESS_ENTRY", "")
version = os.environ.get("INTUITION_VERSION", "unknown")
frontend_path = Path("/app/frontend")

logger.info(f"Intuition v{version} — ingress: {ingress_entry}")


# ── App state ──────────────────────────────────────────────────────────────────
class AppState:
    def __init__(self):
        self.ha_info = {}
        self.entities = []
        self.areas = []
        self.config_files = {}
        self.config_metadata = {}
        self.dependency_map = {}
        self.logs = ""
        self.host_info = {}
        self.core_info = {}
        self.integration_issues = []
        self.loaded = False

state = AppState()


# ── Startup ────────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Intuition starting up...")
    await load_all_data()
    yield
    logger.info("Intuition shutting down.")


async def load_all_data():
    try:
        logger.info("Loading HA info...")
        state.ha_info = await ha_client.get_ha_info()

        logger.info("Loading entities...")
        state.entities = await ha_client.get_states()

        logger.info("Loading areas...")
        state.areas = await ha_client.get_area_registry()

        logger.info("Discovering config files...")
        discovered = ha_client.discover_config_files()
        state.config_files = {k: v["content"] for k, v in discovered.items()}
        state.config_metadata = {k: {
            "key": v["key"], "type": v["type"],
            "lines": v["lines"], "path": v.get("path", ""),
        } for k, v in discovered.items()}

        logger.info("Building dependency map...")
        state.dependency_map = ha_client.build_dependency_map(discovered)

        logger.info("Checking integration health...")
        state.integration_issues = await ha_client.get_integration_issues()
        if state.integration_issues:
            logger.warning(f"Found {len(state.integration_issues)} integration(s) with issues")

        logger.info("Loading logs...")
        state.logs = await ha_client.get_error_log()

        logger.info("Loading system info...")
        state.host_info = await ha_client.get_host_info()
        state.core_info = await ha_client.get_core_info()

        state.loaded = True
        logger.info(f"Startup complete. {len(state.entities)} entities, {len(state.config_files)} config files.")
    except Exception as e:
        logger.error(f"Error during startup: {e}")
        state.loaded = True


# ── FastAPI app ────────────────────────────────────────────────────────────────
app = FastAPI(title="Intuition", lifespan=lifespan, root_path=ingress_entry)


# ── Frontend ───────────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    index = frontend_path / "index.html"
    if index.exists():
        html = index.read_text()
        html = html.replace("const BASE_PATH_PLACEHOLDER = '';", f"const BASE_PATH_PLACEHOLDER = '{ingress_entry}';")
        html = html.replace("const VERSION_PLACEHOLDER = '';", f"const VERSION_PLACEHOLDER = '{version}';")
        return HTMLResponse(content=html)
    return HTMLResponse(content="<h1>Intuition</h1><p>Frontend not found.</p>")


# ── Status ─────────────────────────────────────────────────────────────────────
@app.get("/api/status")
async def get_status():
    ha_version = (
        state.ha_info.get("version") or
        state.core_info.get("data", {}).get("version") or
        "unknown"
    )
    return {
        "loaded": state.loaded,
        "version": version,
        "ha_version": ha_version,
        "entity_count": len(state.entities),
        "area_count": len(state.areas),
        "files_loaded": list(state.config_files.keys()),
        "files_count": len(state.config_files),
        "claude_configured": claude_client.is_configured(),
        "integration_issues": len(state.integration_issues),
    }


@app.post("/api/refresh")
async def refresh_data():
    await load_all_data()
    return {"success": True}


# ── Health: live status scan (no AI) ──────────────────────────────────────────
@app.post("/api/health/status")
async def health_status():
    """
    Fast local health scan — no AI, no cost.
    Refreshes all data then returns structured findings.
    """
    await load_all_data()

    # Scan logs for error/warning counts
    log_errors = 0
    log_warnings = 0
    log_critical = False
    if state.logs:
        for line in state.logs.split("\n"):
            ll = line.lower()
            if "critical" in ll:
                log_critical = True
                log_errors += 1
            elif "error" in ll:
                log_errors += 1
            elif "warning" in ll:
                log_warnings += 1

    # Entity health
    all_unavailable = [
        e["entity_id"] for e in state.entities
        if e["state"] in ["unavailable", "unknown"]
    ]
    mobile_unavailable = [
        e for e in all_unavailable
        if any(x in e for x in ["iphone", "ipad", "android", "_phone", "mobile_app"])
    ]
    core_unavailable = [e for e in all_unavailable if e not in mobile_unavailable]

    # Overall system status
    has_errors = bool(state.integration_issues) or log_critical or len(core_unavailable) > 5
    has_warnings = log_errors > 0 or len(core_unavailable) > 0

    if has_errors:
        system_status = "error"
    elif has_warnings:
        system_status = "warn"
    else:
        system_status = "ok"

    # HA version
    ha_version = (
        state.ha_info.get("version") or
        state.core_info.get("data", {}).get("version") or
        "unknown"
    )

    return {
        "system": {
            "status": system_status,
            "ha_version": ha_version,
            "entity_count": len(state.entities),
        },
        "integrations": {
            "status": "error" if state.integration_issues else "ok",
            "total": len(state.integration_issues),
            "issues": state.integration_issues,
        },
        "entities": {
            "status": "warn" if core_unavailable else "ok",
            "total": len(state.entities),
            "unavailable_total": len(all_unavailable),
            "unavailable_core": core_unavailable[:10],
            "unavailable_mobile": len(mobile_unavailable),
        },
        "logs": {
            "status": "error" if log_critical or log_errors > 10 else "warn" if log_errors > 0 else "ok",
            "errors": log_errors,
            "warnings": log_warnings,
            "critical": log_critical,
            "recommend_log_review": log_errors > 0,
        },
        "config": {
            "files_loaded": len(state.config_files),
        },
    }


# ── Health: AI analysis ────────────────────────────────────────────────────────
@app.post("/api/health/ai")
async def health_ai():
    """
    AI-powered health analysis. Sends only structured findings — not full YAML.
    Must call /api/health/status first to get current data.
    """
    # Build structured findings to send to Claude
    # Scan logs
    log_errors = 0
    log_warnings = 0
    error_samples = []
    if state.logs:
        for line in state.logs.split("\n"):
            ll = line.lower()
            if "error" in ll or "critical" in ll:
                log_errors += 1
                if len(error_samples) < 10:
                    error_samples.append(line.strip()[:200])
            elif "warning" in ll:
                log_warnings += 1

    all_unavailable = [
        e["entity_id"] for e in state.entities
        if e["state"] in ["unavailable", "unknown"]
    ]
    core_unavailable = [
        e for e in all_unavailable
        if not any(x in e for x in ["iphone", "ipad", "android", "_phone", "mobile_app"])
    ]

    ha_version = (
        state.ha_info.get("version") or
        state.core_info.get("data", {}).get("version") or
        "unknown"
    )

    findings = {
        "ha_version": ha_version,
        "entity_count": len(state.entities),
        "integration_issues": state.integration_issues,
        "unavailable_core_entities": core_unavailable[:20],
        "unavailable_mobile_count": len(all_unavailable) - len(core_unavailable),
        "log_error_count": log_errors,
        "log_warning_count": log_warnings,
        "log_error_samples": error_samples,
        "config_files_loaded": len(state.config_files),
        "config_file_names": list(state.config_files.keys()),
        "host": state.host_info.get("data", {}),
    }

    try:
        return await claude_client.health_ai(findings)
    except Exception as e:
        return {"error": str(e)}


# ── Entities ───────────────────────────────────────────────────────────────────
@app.get("/api/entities")
async def get_entities(domain: Optional[str] = None, search: Optional[str] = None):
    entities = state.entities
    if domain:
        entities = [e for e in entities if e["entity_id"].startswith(f"{domain}.")]
    if search:
        s = search.lower()
        entities = [e for e in entities if
                    s in e["entity_id"].lower() or
                    s in e.get("attributes", {}).get("friendly_name", "").lower()]
    return {
        "count": len(entities),
        "entities": [
            {
                "entity_id": e["entity_id"],
                "friendly_name": e.get("attributes", {}).get("friendly_name", ""),
                "state": e["state"],
                "domain": e["entity_id"].split(".")[0],
            }
            for e in entities
        ],
    }


@app.get("/api/entities/summary")
async def get_entity_summary():
    domains = {}
    for e in state.entities:
        d = e["entity_id"].split(".")[0]
        domains[d] = domains.get(d, 0) + 1
    unavailable = sum(1 for e in state.entities if e["state"] in ["unavailable", "unknown"])
    return {
        "total": len(state.entities),
        "unavailable": unavailable,
        "domains": dict(sorted(domains.items(), key=lambda x: x[1], reverse=True)),
    }


# ── Config files ───────────────────────────────────────────────────────────────
@app.get("/api/files")
async def get_files():
    files_info = {}
    for name, content in state.config_files.items():
        meta = state.config_metadata.get(name, {})
        files_info[name] = {
            "loaded": True,
            "lines": len(content.split("\n")),
            "size": len(content),
            "key": meta.get("key", "unknown"),
            "type": meta.get("type", "unknown"),
        }
    return {"files": files_info, "total": len(files_info)}


@app.get("/api/files/{filename:path}")
async def get_file(filename: str):
    content = state.config_files.get(filename)
    if content is None:
        raise HTTPException(status_code=404, detail=f"{filename} not loaded.")
    meta = state.config_metadata.get(filename, {})
    return {
        "filename": filename, "content": content,
        "lines": len(content.split("\n")),
        "key": meta.get("key", "unknown"), "type": meta.get("type", "unknown"),
    }


class FileWriteRequest(BaseModel):
    content: str


@app.post("/api/files/{filename:path}")
async def write_file(filename: str, body: FileWriteRequest):
    success = await ha_client.write_config_file(filename, body.content)
    if success:
        state.config_files[filename] = body.content
        return {"success": True, "message": f"{filename} written."}
    raise HTTPException(status_code=500, detail=f"Failed to write {filename}.")


# ── Config check ───────────────────────────────────────────────────────────────
@app.post("/api/config/check")
async def config_check():
    return await ha_client.run_config_check()


# ── Reload ─────────────────────────────────────────────────────────────────────
class ReloadRequest(BaseModel):
    domains: List[str]


@app.post("/api/reload")
async def reload_domains(body: ReloadRequest):
    results = {}
    for domain in body.domains:
        success = await ha_client.reload_domain(domain)
        results[domain] = "reloaded" if success else "failed"
    return {"results": results}


# ── Logs ───────────────────────────────────────────────────────────────────────
@app.get("/api/logs")
async def get_logs(refresh: bool = False):
    if refresh:
        state.logs = await ha_client.get_error_log()
    return {"content": state.logs, "lines": len(state.logs.split("\n")) if state.logs else 0}


# ── AI: Log review ─────────────────────────────────────────────────────────────
@app.post("/api/ai/analyze-logs")
async def analyze_logs(refresh: bool = False):
    if refresh or not state.logs:
        state.logs = await ha_client.get_error_log()
    if not state.logs:
        return {"error": "No logs available."}
    try:
        return await claude_client.analyze_logs(state.logs)
    except Exception as e:
        return {"error": str(e)}


# ── System ─────────────────────────────────────────────────────────────────────
@app.get("/api/system")
async def get_system_info():
    return {
        "version": version,
        "ha": state.ha_info,
        "host": state.host_info.get("data", {}),
        "core": state.core_info.get("data", {}),
        "dependency_map": state.dependency_map,
    }


# ── Main ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8099, log_level=log_level.lower(), access_log=True)
