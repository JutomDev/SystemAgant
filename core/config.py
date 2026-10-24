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


def load_env_file(env_path: Path) -> None:
    """Minimal zero-dependency .env loader."""
    if not env_path.is_file():
        return
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip("\"'")
            if k not in os.environ:
                os.environ[k] = v


def get_config() -> AppConfig:
    """Load configuration from environment variables with .env support."""
    # Attempt to load local .env if present
    load_env_file(Path(".env"))

    raw_mode = os.getenv("EXECUTION_MODE", "simulation").lower()
    valid_modes = {"simulation", "gemini-free", "vertex"}
    mode = raw_mode if raw_mode in valid_modes else "simulation"

    return AppConfig(
        mode=mode,  # type: ignore[arg-type]
        gemini_api_key=os.getenv("GEMINI_API_KEY"),
        gcp_project_id=os.getenv("GCP_PROJECT_ID"),
        gcp_location=os.getenv("GCP_LOCATION", "global"),
        web_host=os.getenv("WEB_HOST", "127.0.0.1"),
        web_port=int(os.getenv("WEB_PORT", "8000")),
        workspaces_dir=Path(os.getenv("WORKSPACES_DIR", "./workspaces")),
        plans_dir=Path(os.getenv("PLANS_DIR", "./plans")),
    )
