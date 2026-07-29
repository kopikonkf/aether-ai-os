"""
Unified Configuration Management for Aether Core
===============================================
Loads configuration from environment variables, .env file, and settings.yaml.
"""

import os
from pathlib import Path
from typing import Any, Dict
import yaml

from aether.paths import get_paths


def load_yaml_config(config_path: Path | None = None) -> Dict[str, Any]:
    """Load settings from YAML configuration file."""
    if config_path is None:
        config_path = Path(__file__).parent.parent.parent / "config" / "settings.yaml"
    
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


class Settings:
    """Settings class providing access to environment and yaml configurations."""

    def __init__(self):
        self.paths = get_paths()
        self._yaml_config = load_yaml_config()
        
    @property
    def host(self) -> str:
        return os.getenv("HOST", self._yaml_config.get("server", {}).get("host", "0.0.0.0"))

    @property
    def port(self) -> int:
        return int(os.getenv("PORT", self._yaml_config.get("server", {}).get("port", 8001)))

    @property
    def debug(self) -> bool:
        return os.getenv("DEBUG", str(self._yaml_config.get("server", {}).get("debug", False))).lower() in ("true", "1", "yes")

    @property
    def mcp_mode(self) -> str:
        return os.getenv("MCP_MODE", self._yaml_config.get("mcp", {}).get("mode", "pass_through"))

    @property
    def auth_secret_key(self) -> str:
        return os.getenv("AUTH_SECRET_KEY", "change-me-in-production")

    @property
    def database_path(self) -> Path:
        env_db = os.getenv("DATABASE_PATH")
        if env_db:
            return Path(env_db)
        return self.paths.aether_hub_db


settings = Settings()
