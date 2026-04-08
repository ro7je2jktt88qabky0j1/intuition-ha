"""
Intuition - Your home just knows.
FastAPI backend with HA ingress support and dynamic config discovery.
"""

import os
import logging
from pathlib import Path
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
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
        self.config_files = {}       # filename -> content string
        self.config_metadata = {}    # filename -> {key, type, lines, path}
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
            "key": v["key"],
            "type": v["type"],
            "lines": v["lines"],
            "path": v.get("path", ""),
        } for k, v in discovered.items()}

        logger.info("Building dependency map...")
        state.dependency_map = ha_client.build_dependency_map(discovered)

        logger.info("Checking integration health...")
        state.integration_issues = await ha_client.get_integration_issues()
        if state.integration_issues:
            logger.warning(f"Found {len(state.integration_issues)} integration(s) with issues: {[i['title'] for i in state.integration_issues]}")

        logger.info("Loading logs...")
        state.logs = await ha_client.get_error_log()

        logger.info("Loading system info...")
        state.host_info = await ha_client.get_host_info()
        state.core_info = await ha_client.get_core_info()

        state.loaded = True
        logger.info(
            f"Startup complete. {len(state.entities)} entities, "
            f"{len(state.config_files)} config files loaded."
        )
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
        html = html.replace(
            "const BASE_PATH_PLACEHOLDER = '';",
            f"const BASE_PATH_PLACEHOLDER = '{ingress_entry}';"
        )
        html = html.replace(
            "const VERSION_PLACEHOLDER = '';",
            f"const VERSION_PLACEHOLDER = '{version}';"
        )
        return HTMLResponse(content=html)
    return HTMLResponse(content="<h1>Intuition</h1><p>Frontend not found.</p>")


# ── Status ─────────────────────────────────────────────────────────────────────
@app.get("/api/status")
async def get_status():
    ha_version = (
        state.ha_info.get("version") or
        state.core_info.get("data", {}).get("version") or
        state.core_info.get("version") or
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
    return {
        "files": files_info,
        "total": len(files_info),
    }


@app.get("/api/files/{filename:path}")
async def get_file(filename: str):
    content = state.config_files.get(filename)
    if content is None:
        raise HTTPException(status_code=404, detail=f"{filename} not loaded.")
    meta = state.config_metadata.get(filename, {})
    return {
        "filename": filename,
        "content": content,
        "lines": len(content.split("\n")),
        "key": meta.get("key", "unknown"),
        "type": meta.get("type", "unknown"),
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
    return {
        "content": state.logs,
        "lines": len(state.logs.split("\n")) if state.logs else 0,
    }


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


# ── AI: Health check ───────────────────────────────────────────────────────────
@app.post("/api/ai/health-check")
async def run_health_check(refresh: bool = False):
    if refresh:
        await load_all_data()
    try:
        return await claude_client.health_check(
            files=state.config_files,
            file_metadata=state.config_metadata,
            entities=state.entities,
            areas=state.areas,
            logs=state.logs,
            host_info=state.host_info,
            core_info=state.core_info,
            integration_issues=state.integration_issues,
        )
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
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8099,
        log_level=log_level.lower(),
        access_log=True,
    )
