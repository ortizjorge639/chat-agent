# ══════════════════════════════════════════════════════════════════
# setup_demo.ps1 — Extron Part Replacement Intelligence Demo Setup
# ══════════════════════════════════════════════════════════════════
#
# WHAT THIS DOES
# ──────────────
# Rather than using the Data Agent in Fabric, Maciej built a custom
# AI agent programmatically using Azure OpenAI's GPT-5-mini model
# and Python.
#
# The agent was crafted through prompt and context engineering — a
# carefully designed system prompt tells the model exactly how to
# detect replacement intent and extract part numbers from free-text
# comments. This prompt does most of the heavy lifting.
#
# The Python script (demo.py) then:
#   1. Reads each record from a data frame (Excel spreadsheet)
#   2. Sends the comment text to the AI agent for analysis
#   3. Receives structured results: replacement intent, old/new
#      part numbers, cue phrases, confidence scores, and rationale
#   4. Writes an updated spreadsheet with all extracted results
#
# THIS SETUP SCRIPT provisions the Azure OpenAI resources needed
# to power that agent. Run it once before the demo, tear down after.
# ══════════════════════════════════════════════════════════════════

# ---------- Configuration ----------
$RESOURCE_GROUP   = "rg-extron-demo-temp"
$LOCATION         = "eastus2"
$AOAI_ACCOUNT     = "aoai-extron-demo-temp"
$DEPLOYMENT_NAME  = "gpt-5-mini"
$MODEL_NAME       = "gpt-5-mini"
$MODEL_VERSION    = "2025-08-07"
$SKU              = "GlobalStandard"
$CAPACITY         = 10

# ---------- Step 1: Verify Azure access ----------
# Ensures we're logged into the right Azure subscription
Write-Host "`n=== Checking Azure CLI login ===" -ForegroundColor Cyan
$account = az account show 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "Not logged in. Launching az login..." -ForegroundColor Yellow
    az login
}
$sub = az account show --query "{name:name, id:id}" -o tsv
Write-Host "Active subscription: $sub" -ForegroundColor Green

# ---------- Step 2: Create a temporary resource group ----------
# A container for all demo resources — easy to delete everything at once
Write-Host "`n=== Creating resource group: $RESOURCE_GROUP ===" -ForegroundColor Cyan
az group create --name $RESOURCE_GROUP --location $LOCATION -o none

# ---------- Step 3: Provision the Azure OpenAI service ----------
# This is the AI backend that powers the custom extraction agent
Write-Host "`n=== Creating Azure OpenAI account: $AOAI_ACCOUNT ===" -ForegroundColor Cyan
az cognitiveservices account create `
    --name $AOAI_ACCOUNT `
    --resource-group $RESOURCE_GROUP `
    --location $LOCATION `
    --kind OpenAI `
    --sku S0 `
    --custom-domain $AOAI_ACCOUNT `
    -o none

# ---------- Step 4: Deploy the GPT-5-mini model ----------
# This is the specific model Maciej selected for the agent —
# it balances speed, cost, and accuracy for high-volume extraction
Write-Host "`n=== Deploying model: $MODEL_NAME as '$DEPLOYMENT_NAME' ===" -ForegroundColor Cyan
az cognitiveservices account deployment create `
    --name $AOAI_ACCOUNT `
    --resource-group $RESOURCE_GROUP `
    --deployment-name $DEPLOYMENT_NAME `
    --model-name $MODEL_NAME `
    --model-version $MODEL_VERSION `
    --model-format OpenAI `
    --sku-name $SKU `
    --sku-capacity $CAPACITY `
    -o none

# ---------- Step 5: Retrieve the connection credentials ----------
# The script needs an endpoint URL and API key to talk to the model
Write-Host "`n=== Retrieving credentials ===" -ForegroundColor Cyan
$endpoint = az cognitiveservices account show `
    --name $AOAI_ACCOUNT `
    --resource-group $RESOURCE_GROUP `
    --query "properties.endpoint" -o tsv

$key = az cognitiveservices account keys list `
    --name $AOAI_ACCOUNT `
    --resource-group $RESOURCE_GROUP `
    --query "key1" -o tsv

# ---------- Step 6: Write the configuration file ----------
# Saves credentials so the Python agent (demo.py) can connect to the model
$envPath = Join-Path $PSScriptRoot ".env"
@"
AZURE_OPENAI_ENDPOINT=$endpoint
AZURE_OPENAI_CHAT_DEPLOYMENT=$DEPLOYMENT_NAME
AZURE_OPENAI_API_KEY=$key
INPUT_XLSX=component_comments_with_prediction_columns_sample25.xlsx
OUTPUT_XLSX=output.xlsx
TEXT_COLUMN=Comments
"@ | Set-Content -Path $envPath -Encoding UTF8

Write-Host "`n=== .env written to: $envPath ===" -ForegroundColor Green
Write-Host "Endpoint : $endpoint"
Write-Host "Deployment: $DEPLOYMENT_NAME"
Write-Host "Key      : $($key.Substring(0,8))..." -ForegroundColor DarkGray

# ---------- Ready! ----------
# The custom AI agent (demo.py) is now connected to Azure OpenAI.
# It will process each comment, detect replacement intent, extract
# part numbers, and produce a confidence-scored spreadsheet.
Write-Host "`n=== Setup complete! Run the demo with: python demo.py ===" -ForegroundColor Green
Write-Host "`nTo tear down all temp resources after the demo:" -ForegroundColor Yellow
Write-Host "  az group delete --name $RESOURCE_GROUP --yes --no-wait" -ForegroundColor Yellow
