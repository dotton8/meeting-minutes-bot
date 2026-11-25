#!/bin/bash
# Part A: provision Speech (F0), Language (F0), Log Analytics and Application Insights.
# Run from the project root after `az login`. Writes keys straight into .env (never committed).
set -euo pipefail

RG=cs345-speech-rg
LOC=${LOC:-westus2}   # Azure for Students only allows a few regions; eastus is blocked

az group create --name "$RG" --location "$LOC" --output none

az cognitiveservices account create --name cs345-speech --resource-group "$RG" \
  --kind SpeechServices --sku F0 --location "$LOC" --yes --output none

az cognitiveservices account create --name cs345-language --resource-group "$RG" \
  --kind TextAnalytics --sku F0 --location "$LOC" --yes --output none

az monitor log-analytics workspace create --resource-group "$RG" \
  --workspace-name cs345-logs --location "$LOC" --output none
WORKSPACE_ID=$(az monitor log-analytics workspace show --resource-group "$RG" \
  --workspace-name cs345-logs --query id --output tsv)

az monitor app-insights component create --app cs345-insights --location "$LOC" \
  --resource-group "$RG" --workspace "$WORKSPACE_ID" --output none

SPEECH_KEY=$(az cognitiveservices account keys list --name cs345-speech \
  --resource-group "$RG" --query key1 --output tsv)
LANG_KEY=$(az cognitiveservices account keys list --name cs345-language \
  --resource-group "$RG" --query key1 --output tsv)
LANG_ENDPOINT=$(az cognitiveservices account show --name cs345-language \
  --resource-group "$RG" --query properties.endpoint --output tsv)
AI_CONN=$(az monitor app-insights component show --app cs345-insights \
  --resource-group "$RG" --query connectionString --output tsv)

cat > .env <<EOF
AZURE_SPEECH_KEY=$SPEECH_KEY
AZURE_SPEECH_REGION=$LOC
AZURE_LANGUAGE_KEY=$LANG_KEY
AZURE_LANGUAGE_ENDPOINT=$LANG_ENDPOINT
APPLICATIONINSIGHTS_CONNECTION_STRING=$AI_CONN
EOF

echo "Done. Keys written to .env. Confirm the tiers:"
az cognitiveservices account list --resource-group "$RG" \
  --query "[].{name:name, kind:kind, sku:sku.name}" --output table
