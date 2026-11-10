# Load environment variables first
from pathlib import Path
from dotenv import load_dotenv

# Explicit root configuration; never search for an upstream backend/.env.
load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=True, interpolate=False)


from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from config import IS_DEBUG_ENABLED
from routes import (
    capabilities,
    screenshot,
    home,
    evals,
    export,
    design_systems,
    prompt_reports,
    agent_runs,
    eval_sets,
)
from uploaded_assets import configure_uploaded_asset_routes
from design2code.routes import router as design2code_router
from design2code.runner import close_previews
from design2code.runs import recover_interrupted_runs

app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
app.include_router(design2code_router)


@app.on_event("shutdown")
async def close_local_previews() -> None:
    close_previews()
configure_uploaded_asset_routes(app)


@app.on_event("startup")
async def log_debug_mode() -> None:
    recover_interrupted_runs()
    debug_status = "ENABLED" if IS_DEBUG_ENABLED else "DISABLED"
    print(f"Backend startup complete. Debug mode is {debug_status}.")


@app.on_event("startup")
async def probe_screenshot_preview_on_startup() -> None:
    # Detect (and warm up) headless Chromium so the screenshot_preview tool is
    # only offered when it can actually run. Logs the outcome.
    from preview_screenshot import probe_screenshot_preview

    await probe_screenshot_preview()

# Configure CORS settings
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add routes
app.include_router(screenshot.router)
app.include_router(home.router)
app.include_router(capabilities.router)
# The local workbench sends model requests only through its tracked Run API.
# Upstream batch-evaluation endpoints use separate model settings and limits.
safe_evals_router = APIRouter()
safe_evals_router.routes = [route for route in evals.router.routes
                            if getattr(route, "path", "") not in {"/run_evals", "/run_evals_stream"}]
app.include_router(safe_evals_router)
app.include_router(export.router)
app.include_router(design_systems.router)
app.include_router(prompt_reports.router)
app.include_router(agent_runs.router)
app.include_router(eval_sets.router)
