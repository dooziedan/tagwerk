"""Application settings, read from environment variables.

Every setting can be overridden with an env var of the same name in upper case,
for example ``MUSIC_DIR=/music``. On Unraid these are the fields in the container template.
"""

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from fastapi import Depends
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Where the music library is mounted inside the container.
    music_dir: Path = Path("/music")
    # Persistent app data: database, logs, settings.
    config_dir: Path = Path("/config")
    log_level: str = "info"

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.config_dir / 'tagwerk.db'}"


@lru_cache
def get_settings() -> Settings:
    return Settings()


SettingsDep = Annotated[Settings, Depends(get_settings)]
