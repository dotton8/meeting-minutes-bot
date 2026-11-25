#!/bin/bash
# Part F (alternative): deploy to Azure Container Apps.
# App Service F1 and B1 quotas are 0 on this Azure for Students subscription in every
# allowed region, so the app runs as a container instead. Container Apps gives the same
# free https://<name>.<region>.azurecontainerapps.io URL with a valid TLS certificate.
#
# Run from the project root after `az login`, once the GitHub Actions build is green.
# Keys are read from your local .env and passed as environment variables; .env is never uploaded.
set -euo pipefail

RG=cs345-speech-rg
LOC=${LOC:-westus2}
APP=${APP:-mmb-ottodh23}
ENV_NAME=${ENV_NAME:-mmb-env}

if [ ! -f .env ]; then echo "Run this from the project root (no .env found)."; exit 1; fi
# Parse .env line by line. Don't `source` it: the App Insights connection string contains
# semicolons, which the shell would treat as command separators and cut the value short.
while IFS= read -r line || [ -n "$line" ]; do
  case "$line" in ''|\#*) continue ;; esac
  key=${line%%=*}; val=${line#*=}
  val=${val%\"}; val=${val#\"}
  export "$key=$val"
done < .env
for v in AZURE_SPEECH_KEY AZURE_SPEECH_REGION AZURE_LANGUAGE_KEY AZURE_LANGUAGE_ENDPOINT \
         APPLICATIONINSIGHTS_CONNECTION_STRING; do
  if [ -z "${!v:-}" ]; then echo "$v is missing from .env"; exit 1; fi
done

echo "== Registering providers (safe to repeat)"
for ns in Microsoft.App Microsoft.OperationalInsights; do
  az provider register --namespace "$ns" --wait
done
az extension add --name containerapp --upgrade --yes --only-show-errors

# The image is built by GitHub Actions and published to GitHub Container Registry,
# because Azure for Students blocks ACR Tasks (cloud builds). Azure only pulls it.
IMAGE=${IMAGE:-ghcr.io/dotton8/meeting-minutes-bot:latest}

echo "== Deploying $IMAGE (2-5 minutes)"
az containerapp up \
  --name "$APP" \
  --resource-group "$RG" \
  --location "$LOC" \
  --environment "$ENV_NAME" \
  --image "$IMAGE" \
  --ingress external \
  --target-port 8000 \
  --env-vars \
    AZURE_SPEECH_KEY="$AZURE_SPEECH_KEY" \
    AZURE_SPEECH_REGION="$AZURE_SPEECH_REGION" \
    AZURE_LANGUAGE_KEY="$AZURE_LANGUAGE_KEY" \
    AZURE_LANGUAGE_ENDPOINT="$AZURE_LANGUAGE_ENDPOINT" \
    APPLICATIONINSIGHTS_CONNECTION_STRING="$APPLICATIONINSIGHTS_CONNECTION_STRING"

FQDN=$(az containerapp show --name "$APP" --resource-group "$RG" \
  --query properties.configuration.ingress.fqdn --output tsv)
echo
echo "Live URL: https://$FQDN"
