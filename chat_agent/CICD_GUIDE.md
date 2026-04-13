# Azure DevOps CI/CD Pipeline — From Zero to Deployment

A step-by-step guide for deploying a Python chat agent to Azure using Bicep (Infrastructure as Code) and Azure DevOps Pipelines.

**What you'll build:**
- Modular Bicep templates for Azure App Service, Bot Service, and OpenAI
- A 3-stage CI/CD pipeline (Build → Deploy Infra → Deploy App)
- An Azure DevOps repo with automated deployments on push to `main`

**Prerequisites:**
- Azure subscription with an existing resource group
- Azure DevOps organization and project
- Azure CLI installed locally
- Git installed locally
- Python 3.11+

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Install Bicep CLI](#2-install-bicep-cli)
3. [Create the Bicep Modules](#3-create-the-bicep-modules)
4. [Create the Pipeline YAML](#4-create-the-pipeline-yaml)
5. [Set Up Azure DevOps](#5-set-up-azure-devops)
6. [Push Code to Azure Repos](#6-push-code-to-azure-repos)
7. [Create and Run the Pipeline](#7-create-and-run-the-pipeline)
8. [Troubleshooting](#8-troubleshooting)
9. [Key Concepts Explained](#9-key-concepts-explained)

---

## 1. Architecture Overview

### Repo Structure

```
repo root/
├── azure-pipelines.yml          ← CI/CD pipeline definition
├── main.py                      ← Python app entry point
├── requirements.txt
├── bot/                         ← Bot Framework handler
├── agent/                       ← AI agent logic
├── config/                      ← App settings (reads env vars)
├── wheels/                      ← Local .whl packages
└── infra/                       ← Infrastructure as Code
    ├── main.bicep               ← Orchestrator (calls modules)
    ├── parameters.json          ← Environment-specific values
    └── modules/
        ├── appservice/
        │   └── appservice.bicep ← Linux App Service + Python 3.11
        ├── botservice/
        │   └── botservice.bicep ← Bot registration + Teams/Web Chat channels
        └── openai/
            └── openai.bicep     ← References existing OpenAI resource
```

### Pipeline Flow

```
git push to main
    │
    ▼
┌─────────────────────┐
│  Stage 1: BUILD     │
│  • Validate Bicep   │
│  • Install Python   │
│  • Zip app code     │
│  • Publish artifacts│
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│  Stage 2: INFRA     │
│  • Deploy Bicep     │
│  • Create/update    │
│    App Service,     │
│    Bot Service      │
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│  Stage 3: APP       │
│  • Zip deploy to    │
│    App Service      │
│  • App restarts     │
└─────────────────────┘
```

### Why Zip Deploy (not Git-based deploy)?

| | Zip Deploy (recommended) | Git-based deploy |
|---|---|---|
| **Build control** | You control the build in the pipeline | App Service builds it (less control) |
| **Local .whl files** | Works — included in the zip | Tricky — Oryx may not find them |
| **Speed** | Faster — prebuilt package | Slower — builds on every deploy |
| **Reproducibility** | Same zip → same result everywhere | Build can vary by server state |
| **Multi-stage** | Build once, deploy same zip to each env | Rebuild from source each time |

---

## 2. Install Bicep CLI

Bicep is a domain-specific language for defining Azure resources. It compiles down to ARM templates but is far more readable.

```bash
# Install Bicep as an Azure CLI extension
az bicep install

# Verify installation
az bicep version
```

---

## 3. Create the Bicep Modules

### 3a. App Service Module (`infra/modules/appservice/appservice.bicep`)

This creates a Linux App Service Plan + Web App configured for Python 3.11.

**Key points:**
- `kind: 'linux'` + `reserved: true` on the plan — **required** for Linux. Without `reserved: true`, you silently get Windows.
- `linuxFxVersion: 'PYTHON|3.11'` — sets the Python runtime.
- `appCommandLine: 'python main.py'` — tells App Service how to start your app. Without this, Azure guesses (usually gunicorn) and your aiohttp app won't start.
- `@secure()` on password parameters — prevents values from appearing in deployment logs.
- App settings are separated into their own resource for easier management. They become environment variables your Python code reads.

```bicep
// Parameters — inputs from parent module (like function arguments)
param appServiceName string
param location string
param skuName string = 'B1'        // B1 ≈ $13/month
param azureOpenAiEndpoint string
@secure()
param azureOpenAiApiKey string
// ... other params

// App Service Plan — the "server" hosting your app
resource appServicePlan 'Microsoft.Web/serverfarms@2022-09-01' = {
  name: '${appServiceName}-plan'
  location: location
  kind: 'linux'
  sku: { name: skuName }
  properties: {
    reserved: true       // REQUIRED for Linux
  }
}

// App Service — your web application
resource appService 'Microsoft.Web/sites@2022-09-01' = {
  name: appServiceName
  location: location
  kind: 'app,linux'
  properties: {
    serverFarmId: appServicePlan.id
    httpsOnly: true
    siteConfig: {
      linuxFxVersion: 'PYTHON|3.11'
      appCommandLine: 'python main.py'
      alwaysOn: true
    }
  }
}

// App Settings — become environment variables
resource appSettings 'Microsoft.Web/sites/config@2022-09-01' = {
  parent: appService
  name: 'appsettings'
  properties: {
    AZURE_OPENAI_ENDPOINT: azureOpenAiEndpoint
    AZURE_OPENAI_API_KEY: azureOpenAiApiKey
    // ...
  }
}

output appServiceUrl string = 'https://${appService.properties.defaultHostName}'
```

### 3b. Bot Service Module (`infra/modules/botservice/botservice.bicep`)

This **registers** a bot with the Bot Framework. It doesn't run code — it tells Azure: "when a user sends a message via Teams/Web Chat, forward it to `<messagingEndpoint>`."

```bicep
param botName string
param messagingEndpoint string    // e.g. https://app-contoso-dev.azurewebsites.net/api/messages
param microsoftAppId string

resource bot 'Microsoft.BotService/botServices@2022-09-15' = {
  name: botName
  location: 'global'              // Bot Service is always global
  kind: 'azurebot'
  sku: { name: 'F0' }            // F0 = Free (10k messages/month)
  properties: {
    endpoint: messagingEndpoint
    msaAppId: microsoftAppId
    msaAppType: 'SingleTenant'
  }
}

// Enable Teams and Web Chat channels
resource teamsChannel 'Microsoft.BotService/botServices/channels@2022-09-15' = { ... }
resource webChatChannel 'Microsoft.BotService/botServices/channels@2022-09-15' = { ... }
```

### 3c. OpenAI Module (`infra/modules/openai/openai.bicep`)

If you already have an Azure OpenAI resource, use the `existing` keyword to reference it instead of creating a duplicate.

```bicep
param openAiName string

// 'existing' = "don't create this, just look it up"
resource openAi 'Microsoft.CognitiveServices/accounts@2023-05-01' existing = {
  name: openAiName
}

output openAiEndpoint string = openAi.properties.endpoint
```

### 3d. Main Orchestrator (`infra/main.bicep`)

This is the entry point. It calls each module and wires their outputs together — like a `main()` function.

```bicep
targetScope = 'resourceGroup'

param existingOpenAiName string
@secure()
param azureOpenAiApiKey string
// ... other params

var appServiceName = 'app-${projectName}-${environment}'

// Module 1: Look up existing OpenAI
module openAi 'modules/openai/openai.bicep' = {
  params: { openAiName: existingOpenAiName }
}

// Module 2: Create App Service — notice the wiring
module appService 'modules/appservice/appservice.bicep' = {
  params: {
    azureOpenAiEndpoint: openAi.outputs.openAiEndpoint  // ← data flows between modules
    azureOpenAiApiKey: azureOpenAiApiKey
  }
}

// Module 3: Create Bot Service — points at App Service
module botService 'modules/botservice/botservice.bicep' = {
  params: {
    messagingEndpoint: '${appService.outputs.appServiceUrl}/api/messages'
  }
}
```

### 3e. Parameters File (`infra/parameters.json`)

Environment-specific values. Secrets are **NOT** stored here — they come from pipeline variables.

```json
{
  "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#",
  "contentVersion": "1.0.0.0",
  "parameters": {
    "location": { "value": "eastus" },
    "projectName": { "value": "contoso" },
    "environment": { "value": "dev" },
    "existingOpenAiName": { "value": "contoso-openai-demo" },
    "appServiceSku": { "value": "B1" },
    "botServiceSku": { "value": "F0" }
  }
}
```

### Validate Bicep

Always validate before deploying:

```bash
# Compile check (catch syntax errors)
az bicep build --file infra/main.bicep

# Dry-run against Azure (catch resource conflicts)
az deployment group validate \
  --resource-group rg-contoso-demo \
  --template-file infra/main.bicep \
  --parameters @infra/parameters.json \
  --parameters azureOpenAiApiKey='placeholder'
```

---

## 4. Create the Pipeline YAML

The pipeline (`azure-pipelines.yml`) lives at the repo root. Azure DevOps reads it from there.

### Stage 1: Build & Validate

```yaml
stages:
- stage: Build
  jobs:
  - job: ValidateAndPackage
    steps:
    # Validate Bicep
    - task: AzureCLI@2
      inputs:
        azureSubscription: $(azureSubscription)
        scriptType: 'bash'
        inlineScript: |
          az bicep install
          az bicep build --file infra/main.bicep
          az deployment group validate ...

    # Install Python & dependencies
    - task: UsePythonVersion@0
      inputs: { versionSpec: '3.11' }
    - script: pip install -r requirements.txt

    # Package app into zip artifact
    - task: ArchiveFiles@2
      inputs:
        rootFolderOrFile: '$(Build.SourcesDirectory)'
        archiveFile: '$(Build.ArtifactStagingDirectory)/app.zip'

    # Publish artifacts (so later stages can use them)
    - publish: '$(Build.ArtifactStagingDirectory)/app.zip'
      artifact: 'app-package'
    - publish: 'infra'
      artifact: 'infra'
```

**Why publish artifacts?** Each stage runs on a fresh VM. Without publishing, Stage 2 can't access what Stage 1 built.

### Stage 2: Deploy Infrastructure

```yaml
- stage: DeployInfra
  dependsOn: Build
  jobs:
  - job: DeployBicep
    steps:
    - download: current
      artifact: 'infra'

    - task: AzureCLI@2
      inputs:
        inlineScript: |
          az deployment group create \
            --resource-group $(resourceGroupName) \
            --template-file $(Pipeline.Workspace)/infra/main.bicep \
            --parameters $(Pipeline.Workspace)/infra/parameters.json \
            --parameters azureOpenAiApiKey='$(AZURE_OPENAI_API_KEY)' \
            --mode Incremental
```

**`--mode Incremental`** = only add/update resources, never delete. The alternative (`Complete`) deletes anything not in the template — dangerous for a shared resource group.

### Stage 3: Deploy Application

```yaml
- stage: DeployApp
  dependsOn: DeployInfra
  jobs:
  - job: DeployToAppService
    steps:
    - download: current
      artifact: 'app-package'

    - task: AzureWebApp@1
      inputs:
        appType: 'webAppLinux'
        appName: $(appServiceName)
        package: '$(Pipeline.Workspace)/app-package/app.zip'
        runtimeStack: 'PYTHON|3.11'
        startUpCommand: 'python main.py'
```

---

## 5. Set Up Azure DevOps

### 5a. Create a Service Connection

This gives the pipeline permission to deploy to your Azure subscription.

1. Go to **Project Settings → Service connections → New service connection**
2. Choose **Azure Resource Manager → Service principal (automatic)**
3. Select your subscription and resource group
4. Name it (e.g. `service-connection-thursday`)
5. Save

### 5b. Set Pipeline Secret Variables

Secrets must **never** be in YAML or parameters.json. Store them in Azure DevOps:

1. Go to your pipeline → **Edit → Variables → New variable**
2. Add each variable and check **"Keep this value secret"**

| Variable | Where to find it |
|---|---|
| `AZURE_OPENAI_API_KEY` | Azure Portal → your OpenAI resource → Keys and Endpoint |
| `MICROSOFT_APP_ID` | Entra ID → App registrations → Application (client) ID |
| `MICROSOFT_APP_PASSWORD` | Entra ID → App registrations → Certificates & secrets |
| `MICROSOFT_APP_TENANT_ID` | Entra ID → Overview → Tenant ID |

**Tip:** If these values exist in another App Service, pull them via CLI:

```bash
az webapp config appsettings list \
  --name "your-existing-app" \
  --resource-group "your-rg" \
  --query "[?name=='MICROSOFT_APP_ID' || name=='MICROSOFT_APP_PASSWORD' || name=='MICROSOFT_APP_TENANT_ID'].{name:name, value:value}" \
  -o table
```

---

## 6. Push Code to Azure Repos

### 6a. Create the repo

```bash
az repos create \
  --name "chat-agent" \
  --org "https://dev.azure.com/YOUR_ORG" \
  --project "YOUR_PROJECT" \
  --query "remoteUrl" -o tsv
```

### 6b. Initialize and push

```bash
cd your-app-folder

# Create .gitignore (keep secrets and junk out of the repo)
# At minimum, exclude: .env, __pycache__/, .venv/, *.pyc

git init
git add .
git commit -m "Initial commit: app + Bicep IaC + CI/CD pipeline"

# Azure DevOps defaults to 'main', but git init creates 'master'
git branch -M main

# Connect to Azure Repos and push
git remote add origin https://YOUR_ORG@dev.azure.com/YOUR_ORG/YOUR_PROJECT/_git/chat-agent
git push -u origin main
```

---

## 7. Create and Run the Pipeline

### Via CLI

```bash
# Create the pipeline (skip first run to set secrets first)
az pipelines create \
  --name "chat-agent-cicd" \
  --repository "chat-agent" \
  --repository-type tfsgit \
  --branch main \
  --yml-path "azure-pipelines.yml" \
  --org "https://dev.azure.com/YOUR_ORG" \
  --project "YOUR_PROJECT" \
  --skip-first-run true

# After setting secret variables, trigger a run
az pipelines run \
  --name "chat-agent-cicd" \
  --branch main \
  --org "https://dev.azure.com/YOUR_ORG" \
  --project "YOUR_PROJECT"
```

### Via Portal

1. **Pipelines → New Pipeline**
2. **Azure Repos Git → select your repo**
3. **Existing Azure Pipelines YAML file → pick `/azure-pipelines.yml`**
4. **Run**

> **First-run note:** Azure DevOps will ask you to **Permit** the service connection — click allow. This is a one-time authorization.

---

## 8. Troubleshooting

### "No hosted parallelism has been purchased or granted"

New Azure DevOps organizations don't have free hosted build agents by default.

**Options:**
- **Request free parallelism** at https://aka.ms/azpipelines-parallelism-request (approved within 1-3 business days)
- **Use a self-hosted agent** — runs the pipeline on your own machine (immediate, good for dev/demo)

### Pipeline can't find service connection

If a stage fails with a service connection error, go to the pipeline run and click **Permit** on the authorization prompt. This is required the first time a pipeline uses a service connection.

### App Service returns 503 after deploy

- Check startup command matches your app's entry point (`python main.py`)
- Verify `linuxFxVersion` matches your Python version
- Check App Service logs: `az webapp log tail --name app-contoso-dev --resource-group rg-contoso-demo`

### Bicep validation fails

```bash
# Check syntax locally first
az bicep build --file infra/main.bicep

# Dry-run against Azure
az deployment group validate \
  --resource-group rg-contoso-demo \
  --template-file infra/main.bicep \
  --parameters @infra/parameters.json \
  --parameters azureOpenAiApiKey='placeholder'
```

---

## 9. Key Concepts Explained

### Bicep vs ARM Templates
Bicep is a **cleaner syntax** that compiles to ARM JSON. Think of it as TypeScript to JavaScript — same output, better developer experience. Azure CLI handles the compilation automatically during deployment.

### Modules in Bicep
Like functions in code. Each `.bicep` file takes parameters (inputs) and returns outputs. The orchestrator (`main.bicep`) calls modules and wires their outputs together. This keeps templates small, reusable, and testable.

### `existing` keyword
Tells Bicep "this resource already exists — don't create it, just give me its properties." Used when you want to reference a resource without managing its lifecycle (e.g., a shared OpenAI instance).

### Pipeline Artifacts
A zip/folder published by one stage and downloaded by another. Stages run on **separate VMs**, so without artifacts they can't share files. The pattern is: Build once → publish artifact → deploy the same artifact to every environment.

### Service Connection
An Azure DevOps concept that stores credentials for accessing external services (Azure, AWS, etc.). The pipeline references it by name. This avoids putting subscription credentials in YAML.

### Incremental vs Complete deployment mode
- **Incremental** (recommended): Only adds or updates resources defined in the template. Existing resources not in the template are left alone.
- **Complete** (dangerous): Deletes any resource in the resource group that isn't defined in the template. Only use if the template is the single source of truth for the entire resource group.

---

## Tools Used

| Tool | Purpose |
|---|---|
| **Azure CLI** (`az`) | Manage Azure resources, install Bicep, create repos/pipelines |
| **Bicep CLI** | Compile and validate `.bicep` infrastructure templates |
| **Git** | Version control — push code to Azure Repos |
| **Azure DevOps** | Hosts the repo, runs the CI/CD pipeline |
| **Azure App Service** | Hosts the Python web app on Linux |
| **Azure Bot Service** | Routes messages from Teams/Web Chat to the app |
| **Azure OpenAI** | Provides the AI model the chat agent uses |

---

*Guide created April 2026. Based on deploying a Python chat agent with Bot Framework to Azure App Service using modular Bicep IaC and Azure DevOps Pipelines.*
