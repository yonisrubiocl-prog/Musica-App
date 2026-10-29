FROM python:3.12-slim
ENV PIP_ROOT_USER_ACTION=ignore PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONUNBUFFERED=1 PATH=/opt/venv/bin:$PATH
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
# yt-dlp necesita un motor de JavaScript para YouTube
COPY --from=denoland/deno:bin /deno /usr/local/bin/deno
# En un venv del usuario 1000 (el contenedor no corre como root) para poder actualizar yt-dlp al arrancar
RUN python -m venv /opt/venv && pip install --no-cache-dir fastapi "uvicorn[standard]" "yt-dlp[default]" \
    && chown -R 1000:1000 /opt/venv
WORKDIR /app
COPY app.py .
USER 1000:1000
# Cada arranque actualiza yt-dlp: YouTube cambia a menudo y lo rompe.
CMD ["sh", "-c", "pip install -q -U --no-cache-dir 'yt-dlp[default]' || true; exec uvicorn app:app --host 0.0.0.0 --port 8000 --no-access-log"]
