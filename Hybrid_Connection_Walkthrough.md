# Connecting Azure App Service to On-Premises SQL Server via Hybrid Connections

## Overview

This walkthrough demonstrates how to connect an Azure-hosted chat agent (Python, Bot Framework) to an on-premises SQL Server database — **with zero code changes** — using Azure Relay Hybrid Connections.

**Result**: The Azure App Service resolves the on-prem hostname (`jortizflores:1433`) through a secure relay tunnel, enabling the bot to query live data from an internal SQL Server.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           Azure Cloud                                    │
│                                                                         │
│  ┌─────────────────────┐       ┌──────────────────────────────┐        │
│  │  App Service         │       │  Azure Relay                  │        │
│  │  (extron-data-bot)   │──────▶│  (extron-relay namespace)     │        │
│  │  Python 3.11         │       │  sql-hybrid-conn              │        │
│  │  SQL_SERVER=         │       │  endpoint: jortizflores:1433  │        │
│  │   jortizflores       │       └───────────────┬──────────────┘        │
│  └─────────────────────┘                        │                        │
│                                                  │ Port 443 (outbound)   │
└──────────────────────────────────────────────────┼───────────────────────┘
                                                   │
                                                   ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                        On-Premises / Developer Machine                    │
│                                                                          │
│  ┌──────────────────────────┐       ┌──────────────────────────────┐    │
│  │  Hybrid Connection       │       │  SQL Server Express           │    │
│  │  Manager (HCM)           │──────▶│  Port 1433                    │    │
│  │  Windows Service         │       │  Database: ExtronDemo         │    │
│  │  Outbound HTTPS only     │       │  Table: operations.           │    │
│  └──────────────────────────┘       │    Obsolescence_Results       │    │
│                                     └──────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────────┘
```

**Key points**:
- No inbound firewall rules needed — HCM connects outbound on port 443
- No VPN, no ExpressRoute, no public IP on the SQL Server
- App Service sees `jortizflores:1433` as if it were a local hostname
- Cost: ~$10/month (Azure Relay Standard tier)

---

## Prerequisites

| Item | Details |
|------|---------|
| Azure Subscription | Visual Studio Enterprise (or any paid subscription) |
| App Service | Basic tier or higher (Hybrid Connections not available on Free/Shared) |
| SQL Server | Any edition (Express, Standard, Enterprise) with TCP enabled |
| Machine for HCM | Windows machine on same network as SQL Server |
| Outbound port 443 | From HCM machine to `*.servicebus.windows.net` |

---

## Step-by-Step Setup

### Step 1: Configure SQL Server for TCP + SQL Authentication

SQL Server Express often ships with TCP disabled and Windows-only auth. For Hybrid Connections, we need:
- **Static TCP port** (1433) — the relay endpoint targets a fixed port
- **SQL Authentication** — App Service (Linux) cannot use Windows auth

```powershell
# Run elevated (_setup_sql.py or manual):
# 1. Set static TCP port 1433 in registry
# 2. Enable mixed-mode authentication (LoginMode=2)
# 3. Restart SQL Server service
# 4. Create a SQL login with db_datareader

# Verify TCP is working:
Test-NetConnection -ComputerName localhost -Port 1433
# TcpTestSucceeded: True
```

**SQL login created**:
- Username: `extron_bot`
- Role: `db_datareader` on `ExtronDemo`
- Purpose: Read-only access for the bot

---

### Step 2: Create Azure Relay Namespace

```bash
az relay namespace create \
  --name extron-relay \
  --resource-group rg-extron-demo \
  --location centralus
```

Output:
```
Name          ProvisioningState    ServiceBusEndpoint
extron-relay  Succeeded            https://extron-relay.servicebus.windows.net:443/
```

---

### Step 3: Create Hybrid Connection

```bash
az relay hyco create \
  --name sql-hybrid-conn \
  --namespace-name extron-relay \
  --resource-group rg-extron-demo \
  --requires-client-authorization true \
  --user-metadata '[{"key":"endpoint","value":"jortizflores:1433"}]'
```

The `user-metadata` with `endpoint` key tells HCM where to forward traffic.

---

### Step 4: Link Hybrid Connection to App Service

```bash
az webapp hybrid-connection add \
  --name extron-data-bot-app \
  --resource-group rg-extron-demo \
  --namespace extron-relay \
  --hybrid-connection sql-hybrid-conn
```

Output confirms:
```
Hostname      Port    ServiceBusNamespace
jortizflores  1433    extron-relay
```

---

### Step 5: Set App Service Environment Variables

```bash
az webapp config appsettings set \
  --name extron-data-bot-app \
  --resource-group rg-extron-demo \
  --settings \
    DATASOURCE=sql \
    SQL_SERVER=jortizflores \
    SQL_DATABASE=ExtronDemo \
    SQL_TABLE=operations.Obsolescence_Results \
    SQL_TRUSTED_CONNECTION=no \
    SQL_USERNAME=extron_bot \
    SQL_PASSWORD=<password>
```

> **Note**: Changing app settings automatically restarts the App Service. No redeployment needed.

---

### Step 6: Install & Configure Hybrid Connection Manager (HCM)

1. **Download** from Azure Portal: App Services → Networking → Hybrid connections → "Download connection manager"
2. **Install** the `.msi` on the machine where SQL Server is accessible
3. **Open** Hybrid Connection Manager UI
4. **Add connection** using "Enter Manually" with the connection string:

```
Endpoint=sb://extron-relay.servicebus.windows.net/;SharedAccessKeyName=defaultListener;SharedAccessKey=<key>;EntityPath=sql-hybrid-conn
```

To get the connection string:
```bash
# Create a Listen-only auth rule
az relay hyco authorization-rule create \
  --hybrid-connection-name sql-hybrid-conn \
  --namespace-name extron-relay \
  --resource-group rg-extron-demo \
  --name defaultListener \
  --rights Listen

# Get the connection string
az relay hyco authorization-rule keys list \
  --hybrid-connection-name sql-hybrid-conn \
  --namespace-name extron-relay \
  --resource-group rg-extron-demo \
  --name defaultListener \
  --query primaryConnectionString -o tsv
```

> **Tip**: "Enter Manually" is much faster than browsing subscriptions in the GUI.

---

### Step 7: Verify

**HCM service logs** (check Hybrid Connection Manager UI):
```
[INF] [OP: ADD] Operation started for connection extron-relay/sql-hybrid-conn
[INF] Listener online for connection extron-relay/sql-hybrid-conn
```

**Azure Portal** (App Services → Networking → Hybrid connections):
```
Status: Connected
```

**Azure CLI**:
```bash
az relay hyco show --name sql-hybrid-conn --namespace-name extron-relay \
  --resource-group rg-extron-demo --query listenerCount -o tsv
# Output: 1
```

**App Service log stream**:
```
[INFO] data.loader: Loaded SQL table 'operations.Obsolescence_Results' (10 rows, 4 cols)
[INFO] agent.kernel: AgentKernel initialised (deployment=gpt-4o)
```

---

## What Changed (and What Didn't)

| Category | Change | Location |
|----------|--------|----------|
| **Application Code** | None | — |
| **App Service Settings** | 6 new env vars (DATASOURCE, SQL_*) | Portal → Configuration |
| **Azure Resources** | Relay namespace + Hybrid Connection | rg-extron-demo |
| **On-Prem SQL Server** | TCP 1433 enabled, SQL login created | SQL Server Configuration Manager |
| **On-Prem Machine** | HCM installed + configured | Windows Service |

**Key takeaway**: The application code already supported SQL as a data source. The only work was infrastructure configuration — no pipeline run, no code deployment, no PR.

---

## Cost

| Resource | Monthly Cost |
|----------|-------------|
| Azure Relay (Standard) | ~$10/month (includes 5 hybrid connections) |
| App Service (Basic B1) | Already provisioned |
| HCM | Free (Windows service) |

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| Portal shows "Not connected" | HCM GUI crashed during initial setup | Remove & re-add connection in GUI using "Enter Manually" |
| `Login timeout expired` in App Service logs | HCM not connected / SQL Server TCP not enabled | Verify ListenerCount=1, verify port 1433 accessible |
| HCM GUI shows connected but ListenerCount=0 | GUI didn't propagate config to service | Close GUI, restart service, re-add connection |
| `Address already in use (port 5000)` in Event Log | Another process using port 5000 when HCM GUI starts | Kill conflicting process or restart HCM GUI |

---

## For the Customer

When deploying at the customer site, they will need:

1. **SQL Server access** — hostname, port, database name, table/view names
2. **SQL login** — a read-only account (`db_datareader`) for the bot
3. **HCM installed** on a Windows machine that can reach their SQL Server
4. **Outbound port 443** from the HCM machine to `*.servicebus.windows.net`
5. **App Settings updated** with their SQL connection details

No code changes. No VPN. No public endpoints on their SQL Server.

---

## Commands Reference (Quick Copy)

```bash
# Create relay namespace
az relay namespace create --name <relay-name> --resource-group <rg> --location <region>

# Create hybrid connection
az relay hyco create --name <hc-name> --namespace-name <relay-name> --resource-group <rg> \
  --requires-client-authorization true \
  --user-metadata '[{"key":"endpoint","value":"<hostname>:<port>"}]'

# Link to App Service
az webapp hybrid-connection add --name <app-name> --resource-group <rg> \
  --namespace <relay-name> --hybrid-connection <hc-name>

# Set app settings
az webapp config appsettings set --name <app-name> --resource-group <rg> \
  --settings DATASOURCE=sql SQL_SERVER=<hostname> SQL_DATABASE=<db> \
  SQL_TABLE=<schema.table> SQL_TRUSTED_CONNECTION=no \
  SQL_USERNAME=<user> SQL_PASSWORD=<password>

# Create listener auth rule + get connection string (for HCM manual entry)
az relay hyco authorization-rule create --hybrid-connection-name <hc-name> \
  --namespace-name <relay-name> --resource-group <rg> --name defaultListener --rights Listen

az relay hyco authorization-rule keys list --hybrid-connection-name <hc-name> \
  --namespace-name <relay-name> --resource-group <rg> --name defaultListener \
  --query primaryConnectionString -o tsv

# Verify
az relay hyco show --name <hc-name> --namespace-name <relay-name> --resource-group <rg> \
  --query listenerCount -o tsv

# Restart app (after config changes)
az webapp restart --name <app-name> --resource-group <rg>
```
