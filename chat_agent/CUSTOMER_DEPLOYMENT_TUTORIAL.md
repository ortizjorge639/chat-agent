# Deploying Your Chat Agent to Azure with SQL Server

> **Audience:** Customer dev team with a locally working solution  
> **Goal:** Deploy to Azure App Service + connect to Azure SQL — proven working in our demo environment  
> **Prerequisites:** Working local app, Azure subscription, Azure DevOps project

---

## Slide 1 — Title

<!-- SLIDE DESIGN: Dark background (navy #1E2761), large centered title in white, subtitle in ice blue (#CADCFC). Company logos bottom-right. Single hero image or icon of a cloud + database. -->

# From Local to Azure
### Deploying Your Chat Agent with CI/CD and Azure SQL

---

## Slide 2 — What You Already Have (Starting Point)

<!-- SLIDE DESIGN: Light background. Left side: checklist with green checkmarks. Right side: simple architecture diagram showing "Local Machine → Excel files → Chat Agent". Keep it clean, 4-5 bullet max. -->

Your solution is already working locally. Here's what's in place:

- ✅ `main_test.py` — Chat API with download endpoints
- ✅ `agent/kernel_test.py` — Agent kernel with Semantic Kernel
- ✅ `agent/plugins/data_plugin_test.py` — Data tools + Excel export
- ✅ `data/loader.py` — Already supports both Excel and SQL (no changes needed)
- ✅ `config/settings.py` — Already has SQL fields (no changes needed)
- ✅ `requirements.txt` — Already includes `pyodbc>=5.0.0`

**Today we make 1 small code change + set up infrastructure.**

---

## Slide 3 — What We're Doing Today (Overview)

<!-- SLIDE DESIGN: Light background. Center a 3-column layout with icons: (1) wrench icon → "1 Code Fix", (2) pipeline icon → "CI/CD Pipeline", (3) database icon → "Azure SQL". Use accent color (#CADCFC) for icon backgrounds. Below: a horizontal arrow diagram showing the flow. -->

| Step | What | Why |
|------|------|-----|
| **Code Fix** | 1 edit in `main_test.py` (3 lines) | Excel downloads need a writable path on App Service |
| **CI/CD Pipeline** | Add `azure-pipelines.yml` to your repo | Automates build + deploy with a critical cryptography fix |
| **Azure SQL** | Provision server + database, configure app settings | Switch from local Excel to cloud SQL |

---

## Slide 4 — The One Code Change

<!-- SLIDE DESIGN: Dark background. Show a code diff — "before" on top in red/faded, "after" below in green/bright. Use monospace font, large enough to read. Highlight the 3 changed lines. Add a callout box explaining WHY. -->

### File: `main_test.py` (lines 25–28)

**Before:**
```python
GENERATED_DIR = os.path.join(os.path.dirname(__file__), "generated")
```

**After:**
```python
GENERATED_DIR = os.environ.get(
    "GENERATED_DIR",
    os.path.join(os.path.dirname(__file__), "generated"),
)
```

**Why:** App Service deploys your code as a read-only ZIP mount (`runFromPackage`). The `generated/` folder inside the package is not writable. This change lets the app read `GENERATED_DIR` from an environment variable — on Azure it points to `/tmp/generated` (writable). Locally, it falls back to `./generated` so nothing changes for you.

---

## Slide 5 — The CI/CD Pipeline

<!-- SLIDE DESIGN: Light background. Two-column layout: Left = pipeline flow diagram (Build stage → Deploy stage, with sub-steps listed). Right = key callouts in accent-colored boxes explaining the cryptography fix and runFromPackage. -->

### Add `azure-pipelines.yml` to your repo root

The pipeline has **two stages**:

#### Stage 1: Build
1. Use Python 3.11
2. Create virtual environment (`antenv`)
3. Install dependencies from `requirements.txt` + local `wheels/` folder
4. **Critical fix:** Replace the `cryptography` wheel with a `manylinux_2_28` build
5. ZIP everything into a deployable package

#### Stage 2: Deploy
1. Deploy the ZIP to App Service using `runFromPackage`
2. Set startup command: `python main_test.py`
3. Set app settings: `GENERATED_DIR=/tmp/generated`

### Why the cryptography fix matters

The Azure DevOps build agent runs Ubuntu 22.04 (glibc 2.35). It downloads a `manylinux_2_34` cryptography wheel. But App Service runs Debian Bullseye (glibc 2.31). Without the fix, you get:

```
ImportError: /lib/x86_64-linux-gnu/libm.so.6: version `GLIBC_2.33' not found
```

The pipeline forces the `manylinux_2_28` wheel, which is compatible with both.

### Pipeline variables to fill in

```yaml
variables:
  azureSubscription: '<SERVICE-CONNECTION-NAME>'   # Azure DevOps → Project Settings → Service connections
  appServiceName: '<YOUR-APP-SERVICE-NAME>'
```

### Full pipeline file

Copy `azure-pipelines-customer.yml` from the repo and rename it to `azure-pipelines.yml` in your repo root. The trigger is set to `none` by default — uncomment the branch trigger when ready:

```yaml
trigger:
  branches:
    include:
      - main
```

---

## Slide 6 — App Service Configuration

<!-- SLIDE DESIGN: Light background. Show a screenshot placeholder area (annotate: "INSERT SCREENSHOT of App Service → Configuration → App settings"). Below it, a clean table of the required settings. Use color coding: green = new SQL settings, blue = deployment settings, gray = already set. -->

### Required App Settings

Set these on your App Service (Portal → Configuration → Application settings, or via CLI):

| Setting | Value | Notes |
|---------|-------|-------|
| `DATASOURCE` | `sql` | Switches from Excel to SQL |
| `SQL_SERVER` | `<your-server>.database.windows.net` | Azure SQL server FQDN |
| `SQL_DATABASE` | `<your-database>` | Database name |
| `SQL_TABLE` | `<schema>.<table>` | e.g. `operations.Obsolescence_Results` |
| `SQL_USERNAME` | `<admin-user>` | SQL admin username |
| `SQL_PASSWORD` | `<admin-password>` | SQL admin password |
| `SQL_TRUSTED_CONNECTION` | `no` | Must be `no` for Azure SQL (uses username/password) |
| `GENERATED_DIR` | `/tmp/generated` | Writable path for Excel exports |
| `ENABLE_ORYX_BUILD` | `false` | Prevents Oryx from rebuilding and breaking cryptography |

**CLI shortcut:**
```bash
az webapp config appsettings set \
  --name <app-name> \
  --resource-group <resource-group> \
  --settings \
    DATASOURCE=sql \
    SQL_SERVER=<server>.database.windows.net \
    SQL_DATABASE=<database> \
    SQL_TABLE=<schema.table> \
    SQL_USERNAME=<admin> \
    SQL_PASSWORD='<password>' \
    SQL_TRUSTED_CONNECTION=no \
    GENERATED_DIR=/tmp/generated \
    ENABLE_ORYX_BUILD=false
```

---

## Slide 7 — Provision Azure SQL

<!-- SLIDE DESIGN: Light background. Numbered step list on the left with terminal/CLI icons. Right side: diagram showing SQL Server → Database → Firewall Rules. Add a warning callout box about region availability. -->

### Step 1: Create SQL Server

```bash
az sql server create \
  --name <sql-server-name> \
  --resource-group <resource-group> \
  --location <region> \
  --admin-user <admin-username> \
  --admin-password '<strong-password>'
```

> ⚠️ **Region note:** Some regions may reject provisioning for your subscription. If you get `RegionDoesNotAllowProvisioning`, try another region (e.g., `westus3`, `centralus`, `northeurope`).

### Step 2: Create Database

```bash
az sql db create \
  --server <sql-server-name> \
  --resource-group <resource-group> \
  --name <database-name> \
  --edition Basic
```

Basic tier (~$5/mo) is sufficient for demo/dev. Scale up as needed.

### Step 3: Configure Firewall

```bash
# Allow Azure services (required for App Service → SQL)
az sql server firewall-rule create \
  --server <sql-server-name> \
  --resource-group <resource-group> \
  --name AllowAzureServices \
  --start-ip-address 0.0.0.0 \
  --end-ip-address 0.0.0.0

# Allow your dev machine (for loading data)
az sql server firewall-rule create \
  --server <sql-server-name> \
  --resource-group <resource-group> \
  --name DevMachine \
  --start-ip-address <your-public-ip> \
  --end-ip-address <your-public-ip>
```

---

## Slide 8 — Load Your Data

<!-- SLIDE DESIGN: Dark background. Large monospace code block with syntax highlighting. Show the CREATE SCHEMA, CREATE TABLE, and sample INSERT. Add a callout: "Replace with your actual data and schema." -->

### Connect to Azure SQL

```bash
sqlcmd -S "tcp:<server>.database.windows.net,1433" \
  -d "<database>" -U "<admin>" -P "<password>" -N -C
```

> The `-N -C` flags are required for Azure SQL's TLS encryption.

### Create schema and table

```sql
CREATE SCHEMA operations;
GO

CREATE TABLE operations.Obsolescence_Results (
    PartNumber         NVARCHAR(50),
    Status             NVARCHAR(200),
    Details            NVARCHAR(500),
    ModelProcessedDate DATE
);
GO
```

### Insert your data

```sql
INSERT INTO operations.Obsolescence_Results VALUES
('PART-001', 'Active', 'Component in production', '2026-01-15'),
('PART-002', 'End of Life', 'Discontinued Q4 2025', '2026-02-10');
-- ... insert your actual data
GO
```

Adjust the column names and types to match your actual dataset.

---

## Slide 9 — Deploy and Verify

<!-- SLIDE DESIGN: Light background. Three-panel layout: (1) "Push" with git icon, (2) "Pipeline" with build icon + green checkmark, (3) "Verify" with log output. Use a screenshot placeholder for the pipeline run result. -->

### Push your code

```bash
git add azure-pipelines.yml main_test.py
git commit -m "Add CI/CD pipeline and GENERATED_DIR fix for App Service"
git push
```

### Pipeline runs automatically (if trigger is enabled)

Or trigger manually in Azure DevOps → Pipelines → Run pipeline.

### Restart the App Service

```bash
az webapp restart --name <app-name> --resource-group <resource-group>
```

### Verify via container logs

```bash
az webapp log tail --name <app-name> --resource-group <resource-group>
```

**What success looks like:**
```
[INFO] data.loader: Using ODBC driver: ODBC Driver 18 for SQL Server
[INFO] data.loader: Loaded SQL table 'operations.Obsolescence_Results' (X rows, Y cols)
======== Running on http://0.0.0.0:8000 ========
```

---

## Slide 10 — Key Gotchas We Discovered

<!-- SLIDE DESIGN: Light background with warning/tip boxes. Use alternating amber (gotcha) and green (solution) rows. Icon: lightbulb or warning triangle for each. Keep text concise — one line per gotcha/solution pair. -->

| Gotcha | Solution |
|--------|----------|
| `GLIBC_2.33 not found` crash on App Service | Pipeline downloads `manylinux_2_28` cryptography wheel |
| `ENABLE_ORYX_BUILD` re-breaks cryptography | Set `ENABLE_ORYX_BUILD=false` in app settings |
| Excel download returns 404 (`GET /undefined`) | The `GENERATED_DIR` env var fix (Slide 4) |
| ODBC driver not found | **No action needed** — ODBC Driver 18 is pre-installed on App Service Python 3.11 |
| `startup.sh` breaks container warmup | **Don't use a startup script** — just set startup command to `python main_test.py` |
| Azure SQL region provisioning errors | Try multiple regions — availability varies by subscription |
| `sqlcmd` TLS errors connecting to Azure SQL | Use `tcp:` prefix and `-N -C` flags |

---

## Slide 11 — Architecture Summary

<!-- SLIDE DESIGN: Light background. Full-width architecture diagram. Show: User → Bot Service → App Service (Python 3.11) → Azure SQL. Side annotations: "CI/CD via Azure DevOps", "runFromPackage deployment", "ODBC Driver 18 pre-installed". Use cloud/service icons from the Azure icon set. -->

```
┌──────────┐     ┌──────────────┐     ┌─────────────────────────┐     ┌───────────────┐
│  User /  │────▶│ Bot Service  │────▶│  App Service (Linux)    │────▶│  Azure SQL    │
│  Teams   │     │  (global)    │     │  Python 3.11            │     │  Server       │
└──────────┘     └──────────────┘     │  main_test.py           │     │  ┌───────────┐│
                                       │  runFromPackage          │     │  │ Database  ││
                                       │  ODBC Driver 18 built-in │     │  └───────────┘│
                                       └─────────────────────────┘     └───────────────┘
                                                 ▲
                                                 │
                                       ┌─────────────────┐
                                       │  Azure DevOps   │
                                       │  CI/CD Pipeline  │
                                       └─────────────────┘
```

---

## Slide 12 — Recap: What to Do

<!-- SLIDE DESIGN: Dark background (navy). Large numbered list, one item per line, with icons. Bold action verbs. This is the "takeaway" slide — keep it punchy. -->

1. **Edit** `main_test.py` — add `GENERATED_DIR` env var read (3 lines)
2. **Add** `azure-pipelines.yml` — copy from template, fill in your service connection + app name
3. **Provision** Azure SQL Server + Database
4. **Configure** firewall rules (AllowAzureServices + your dev IP)
5. **Load** your data via `sqlcmd`
6. **Set** app settings on App Service (SQL connection, `ENABLE_ORYX_BUILD=false`, `GENERATED_DIR`)
7. **Push** and let the pipeline deploy
8. **Verify** via `az webapp log tail` — look for "Loaded SQL table" message

---

*Screenshots of the working deployment are available upon request.*
