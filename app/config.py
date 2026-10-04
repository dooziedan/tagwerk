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
    # Import inbox: new music waits here until it is tagged and moved into the library.
    # Optional; the Inbox page explains how to set it up when the folder doesn't exist.
    import_dir: Path = Path("/import")
    # Optional: where the original files go after converting tracks to AIFF (app/convert.py).
    # They keep their library path inside it, and wait there for the owner to decide.
    originals_dir: Path = Path("/originals")
    # Persistent app data: database, logs, settings.
    config_dir: Path = Path("/config")
    log_level: str = "info"
    # Optional: Navidrome to rescan after Tagwerk changed files. Use the server's IP address
    # (e.g. http://192.168.1.10:4533), not localhost. The user needs admin rights.
    navidrome_url: str = ""
    navidrome_user: str = ""
    navidrome_password: str = ""
    # With several Navidrome libraries: the name of the one Tagwerk works on (only it is
    # rescanned). Empty: all libraries are rescanned.
    navidrome_library: str = ""

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.config_dir / 'tagwerk.db'}"


@lru_cache
def get_settings() -> Settings:
    return Settings()


SettingsDep = Annotated[Settings, Depends(get_settings)]
