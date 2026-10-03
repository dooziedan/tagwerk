# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.0] - 2026-10-03

### Added
- Project setup: FastAPI app, start page with a setup check for the music and app data folders.
- `/health` endpoint and Docker healthcheck; `/api/status` endpoint.
- Docker image with PUID/PGID/UMASK support (Unraid defaults 99/100/022).
- Unraid container template (`unraid/tagwerk.xml`).
- CI (lint + tests), image publishing to GHCR, Dependabot.
- Documentation: README, architecture, development guide, roadmap, decision records.
