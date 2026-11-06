FROM python:3.12-slim
ENV PIP_ROOT_USER_ACTION=ignore PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONUNBUFFERED=1 PATH=/opt/venv/bin:$PATH
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
# yt-dlp necesita un motor de JavaScript para YouTube
COPY --from=denoland/deno:bin /deno /usr/local/bin/deno
# En un venv del usuario 10001 (el contenedor no corre como root ni como lainer) para poder actualizar yt-dlp al arrancar
RUN python -m venv /opt/venv && pip install --no-cache-dir fastapi "uvicorn[standard]" "yt-dlp[default]" google-auth requests httpx ytmusicapi \
    && chown -R 10001:10001 /opt/venv
WORKDIR /app
COPY app.py users.py library.py userdata.py enrich.py precarga.py genres.py recomendar.py versiones.py duplicadas.py discord_dc.py titulos.py canvas.py conectar.py ./
COPY web/ ./web/
USER 10001:10001
# Cada arranque actualiza yt-dlp: YouTube cambia a menudo y lo rompe. app.py escucha en 8000 (app) y 8001 (bot).
CMD ["sh", "-c", "pip install -q -U --no-cache-dir 'yt-dlp[default]' || true; exec python app.py"]
