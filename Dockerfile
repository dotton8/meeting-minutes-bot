# Container image for Azure Container Apps (App Service quota is 0 on this subscription).
FROM python:3.11-slim-bookworm

# ffmpeg converts browser WebM/Opus and MP3 to WAV; libasound2 + ca-certificates + libssl3
# libstdc++6 + libuuid1 are native dependencies of the Azure Speech SDK on Linux.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg libasound2 ca-certificates libssl3 libstdc++6 libuuid1 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

ENV PORT=8000
EXPOSE 8000
CMD ["gunicorn", "--bind=0.0.0.0:8000", "--timeout", "600", "--workers", "1", "--threads", "4", "app:app"]
