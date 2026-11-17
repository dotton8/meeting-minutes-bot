#!/bin/bash
# App Service startup command (Part F). ffmpeg is not on the App Service Python image,
# so install it on every cold start, then start the app with gunicorn.
apt-get update && apt-get install -y ffmpeg
gunicorn --bind=0.0.0.0 --timeout 600 app:app
