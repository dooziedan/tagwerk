FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MUSIC_DIR=/music \
    ORIGINALS_DIR=/originals \
    CONFIG_DIR=/config \
    PUID=99 \
    PGID=100 \
    UMASK=022

WORKDIR /opt/tagwerk

# ffmpeg (with ffprobe) converts lossless tracks to AIFF (app/convert.py, ADR 0013);
# fpcalc (Chromaprint) fingerprints tracks for AcoustID (app/sources/acoustid.py, ADR 0014).
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libchromaprint-tools \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies first so this layer is cached between code changes.
COPY pyproject.toml README.md LICENSE ./
COPY app ./app
RUN pip install .

COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh && mkdir -p /music /config

EXPOSE 8000
VOLUME ["/config"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"

ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
