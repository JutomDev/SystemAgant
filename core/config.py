"""Centralized application configuration.

Adheres to explicit typing, Pydantic v2 validation, and zero hardcoded secrets.
"""

from typing import Literal, Optional
from pathlib import Path
import os
from pydantic import BaseModel, Field


class AppConfig(BaseModel):
    """Runtime configuration for SystemAgant."""

    mode: Literal["gemini-free", "simulation", "vertex"] = Field(
        default="gemini-free",
        description="Execution mode: 'gemini-free' (Google AI Studio API key), 'simulation' (test mock only), or 'vertex' (GCP project).",
    )
    gemini_api_key: Optional[str] = Field(
        default=None,
        description="Google AI Studio Gemini API Key for free tier execution.",
    )
    gemini_model: str = Field(
        default="gemini-flash-lite-latest",
        description="Gemini Flash Lite model for high-speed free tier execution.",
    )
    gcp_project_id: Optional[str] = Field(
        default=None,
        description="Optional GCP Project ID for legacy Vertex AI execution.",
    )
    gcp_location: str = Field(
        default="global",
        description="GCP region or 'global'.",
    )
    web_host: str = Field(
        default="127.0.0.1",
        description="Host interface for the tactile web dashboard.",
    )
    web_port: int = Field(
        default=8000,
        description="Port for the tactile web dashboard.",
    )
    workspaces_dir: Path = Field(
        default=Path("./workspaces"),
        description="Root directory for isolated agent execution workspaces.",
    )
    plans_dir: Path = Field(
        default=Path("./plans"),
        description="Directory storing baseline WBS epics and simulation sequences.",
    )


def load_env_file(env_path: Optional[Path] = None) -> None:
    """Zero-dependency .env file parser and environment populator.
    
    Searches both explicitly provided path and the repository root relative
    to this file location to ensure deterministic discovery across CWD changes.
    """
    candidates = []
    if env_path is not None:
        candidates.append(env_path)
    # Project root discovery ensures .env is located even when CWD is a subdirectory
    project_root = Path(__file__).resolve().parent.parent
    candidates.extend([Path(".env"), project_root / ".env"])

    target_env: Optional[Path] = None
    for cand in candidates:
        if cand.is_file():
            target_env = cand
            break

    if target_env is None:
        return

    with open(target_env, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            # Skip comments and malformed empty lines
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip("\"'")
            # Existing OS environment variables take precedence over .env file values
            if k not in os.environ:
                os.environ[k] = v


def get_config() -> AppConfig:
    """Loads configuration with robust .env discovery and adaptive mode resolution.
    
    Priority resolution:
    1. Explicit EXECUTION_MODE environment variable if valid.
    2. Auto-promote to 'gemini-free' if a GEMINI_API_KEY is detected in environment or .env.
    3. Safe fallback to 'simulation' for zero-cost, zero-token deterministic mock testing.
    """
    load_env_file()

    gemini_key = os.getenv("GEMINI_API_KEY")
    raw_mode = os.getenv("EXECUTION_MODE", "").lower().strip()
    valid_modes = {"simulation", "gemini-free", "vertex"}

    if raw_mode in valid_modes:
        mode = raw_mode
    elif gemini_key and gemini_key.strip():
        # Auto-activate live Gemini mode when key is present without requiring manual flag
        mode = "gemini-free"
    else:
        # Default to safe mock simulation when no credentials are provided
        mode = "simulation"

    return AppConfig(
        mode=mode,  # type: ignore[arg-type]
        gemini_api_key=gemini_key,
        gcp_project_id=os.getenv("GCP_PROJECT_ID"),
        gcp_location=os.getenv("GCP_LOCATION", "global"),
        web_host=os.getenv("WEB_HOST", "127.0.0.1"),
        web_port=int(os.getenv("WEB_PORT", "8000")),
        workspaces_dir=Path(os.getenv("WORKSPACES_DIR", "./workspaces")),
        plans_dir=Path(os.getenv("PLANS_DIR", "./plans")),
    )
