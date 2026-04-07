"""
Intuition - Your home just knows.
FastAPI backend with HA ingress support.
"""

import os
import logging
from pathlib import Path
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
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
logger.info(f"Ingress entry point: {ingress_entry}")

frontend_path = Path("/app/frontend")


class AppState:
    def __init__(self):
        self.ha_info = {}
        self.entities = []
        self.devices = []
        self.areas = []
        self.config_files = {}
        self.logs = ""
        self.host_info = {}
        self.core_info = {}
        self.loaded = False

state = AppState()


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
        logger.info("Loading devices...")
        state.devices = await ha_client.get_device_registry()
        logger.info("Loading areas...")
        state.areas = await ha_client.get_area_registry()
        logger.info("Loading config files...")
        state.config_files = await ha_client.read_all_config_files()
        logger.info("Loading logs...")
        state.logs = await ha_client.get_error_log()
        logger.info("Loading system info...")
        state.host_info = await ha_client.get_host_info()
        state.core_info = await ha_client.get_core_info()
        state.loaded = True
        logger.info(f"Startup complete. {len(state.entities)} entities, {len(state.config_files)} config files loaded.")
    except Exception as e:
        logger.error(f"Error during startup data load: {e}")
        state.loaded = True


# Use ingress entry as root path so all routes work correctly behind the proxy
app = FastAPI(title="Intuition", lifespan=lifespan, root_path=ingress_entry)


@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    index = frontend_path / "index.html"
    if index.exists():
        html = index.read_text()
        # Inject the ingress base path so frontend API calls use the correct URL
        html = html.replace(
            "const BASE_PATH_PLACEHOLDER = '';",
            f"const BASE_PATH_PLACEHOLDER = '{ingress_entry}';"
        )
        return HTMLResponse(content=html)
    return HTMLResponse(content="<h1>Intuition</h1><p>Frontend not found.</p>")


@app.get("/api/status")
async def get_status():
    return {
        "loaded": state.loaded,
        "ha_version": state.ha_info.get("version", "unknown"),
        "entity_count": len(state.entities),
        "device_count": len(state.devices),
        "area_count": len(state.areas),
        "files_loaded": list(state.config_files.keys()),
        "claude_configured": claude_client.is_configured(),
    }


@app.post("/api/refresh")
async def refresh_data():
    await load_all_data()
    return {"success": True, "message": "Data refreshed."}


@app.get("/api/entities")
async def get_entities(domain: Optional[str] = None):
    entities = state.entities
    if domain:
        entities = [e for e in entities if e["entity_id"].startswith(f"{domain}.")]
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
        domain = e["entity_id"].split(".")[0]
        domains[domain] = domains.get(domain, 0) + 1
    unavailable = sum(1 for e in state.entities if e["state"] in ["unavailable", "unknown"])
    return {
        "total": len(state.entities),
        "unavailable": unavailable,
        "domains": dict(sorted(domains.items(), key=lambda x: x[1], reverse=True)),
    }


@app.get("/api/devices")
async def get_devices():
    return {"count": len(state.devices), "devices": state.devices}


@app.get("/api/areas")
async def get_areas():
    return {"count": len(state.areas), "areas": state.areas}


@app.get("/api/files")
async def get_files():
    return {
        "files": {
            name: {"loaded": True, "lines": len(content.split("\n")), "size": len(content)}
            for name, content in state.config_files.items()
        },
        "missing": [f for f in ha_client.CONFIG_FILES if f not in state.config_files],
    }


@app.get("/api/files/{filename}")
async def get_file(filename: str):
    if filename not in ha_client.CONFIG_FILES:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="File not in managed list.")
    content = state.config_files.get(filename)
    if content is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"{filename} not loaded.")
    return {"filename": filename, "content": content, "lines": len(content.split("\n"))}


class FileWriteRequest(BaseModel):
    content: str


@app.post("/api/files/{filename}")
async def write_file(filename: str, body: FileWriteRequest):
    if filename not in ha_client.CONFIG_FILES:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="File not in managed list.")
    success = await ha_client.write_config_file(filename, body.content)
    if success:
        state.config_files[filename] = body.content
        return {"success": True, "message": f"{filename} written."}
    from fastapi import HTTPException
    raise HTTPException(status_code=500, detail=f"Failed to write {filename}.")


@app.post("/api/config/check")
async def config_check():
    return await ha_client.run_config_check()


class ReloadRequest(BaseModel):
    domains: List[str]


@app.post("/api/reload")
async def reload_domains(body: ReloadRequest):
    results = {}
    for domain in body.domains:
        success = await ha_client.reload_domain(domain)
        results[domain] = "reloaded" if success else "failed"
    return {"results": results}


@app.get("/api/logs")
async def get_logs(refresh: bool = False):
    if refresh:
        state.logs = await ha_client.get_error_log()
    return {"content": state.logs, "lines": len(state.logs.split("\n")) if state.logs else 0}


@app.post("/api/ai/analyze-logs")
async def analyze_logs(refresh: bool = False):
    if refresh or not state.logs:
        state.logs = await ha_client.get_error_log()
    if not state.logs:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="No logs available.")
    return await claude_client.analyze_logs(state.logs)


@app.post("/api/ai/health-check")
async def run_health_check(refresh: bool = False):
    if refresh:
        await load_all_data()
    return await claude_client.health_check(
        files=state.config_files,
        entities=state.entities,
        areas=state.areas,
        logs=state.logs,
        host_info=state.host_info,
        core_info=state.core_info,
    )


@app.get("/api/system")
async def get_system_info():
    return {
        "ha": state.ha_info,
        "host": state.host_info.get("data", {}),
        "core": state.core_info.get("data", {}),
    }


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8099,
        log_level=log_level.lower(),
        access_log=True,
    )
