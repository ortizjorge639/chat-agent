# Deployment Troubleshooting Guide
## Python Web Apps on Azure App Service (Linux)

Lessons learned from deploying Python web apps to Azure App Service
(Linux). This guide documents every gotcha we hit and the verified
fix — in the order they'll bite you.

Applies to any Python app deployed via zip to Azure App Service Linux
with Oryx build (aiohttp, Flask, FastAPI, Django, etc.).

---

## 1. Create the Zip Correctly (Windows → Linux Path Issue)

**The problem:** Windows `Compress-Archive` (and right-click → Compress)
writes backslash paths (`config\\settings.py`) into the zip. Linux
treats these as literal filenames — not files inside directories. The
app starts but immediately fails:

```
ModuleNotFoundError: No module named 'config'
```

**How to confirm:** In Kudu SSH, inspect the compressed output:

```bash
zstd -d /home/site/wwwroot/output.tar.zst --stdout | tar -tf - | head -30
```

If you see double backslashes (`./config\\settings.py`), the zip is bad.

**The fix:** Use Python's `zipfile` module to create the zip with
forward-slash paths:

```powershell
# cd INTO your project folder (not its parent)
cd C:\path\to\your-project

# Create the zip (excludes __pycache__ and .pyc files)
python -c "import zipfile, os; z=zipfile.ZipFile(r'C:\Temp\deploy.zip','w',zipfile.ZIP_DEFLATED); [z.write(os.path.join(r,f),os.path.join(r,f).replace(os.sep,'/')) for r,d,fs in os.walk('.') if '__pycache__' not in r for f in fs if not f.endswith('.pyc')]; z.close(); print('Done')"
```

> **Never use `Compress-Archive` or right-click → Compress for Linux
> deployments from Windows.** Always use the Python script above.

---

## 2. requirements.txt Must Be at the Zip Root

**The problem:** If you zip the project folder itself (instead of its
contents), the zip structure is nested:

```
❌ Wrong:                ✅ Correct:
my-project/              requirements.txt
  requirements.txt       main.py
  main.py                config/
  config/                ...
```

Oryx looks for `requirements.txt` at the zip root. If it's nested, Oryx
**skips pip install entirely** — no error, just this in the build log:

```
Could not find requirements.txt, pyproject.toml, or setup.py;
Not installing dependencies.
```

The build "succeeds" in ~30 seconds (suspiciously fast), but nothing is
installed.

**The fix:** Always `cd` into your project folder before creating the
zip. The Python script in section 1 handles this correctly.

**Verify before deploying:** Open the zip in File Explorer:
- `requirements.txt` and your entry point (e.g. `main.py`) are at the
  **root** (not inside a subfolder)
- All subfolders (`config/`, `agent/`, etc.) are visible at the top level

---

## 3. Deploy with config-zip (Not deploy --type zip)

**The problem:** `az webapp deploy --type zip` does not reliably trigger
the Oryx build. Files get copied but `pip install` never runs.

**The fix:**

```powershell
az webapp deployment source config-zip `
  --resource-group <your-resource-group> `
  --name <your-app-service> `
  --src C:\Temp\deploy.zip
```

The CLI warns this is deprecated — **ignore it**. Build takes ~300
seconds for a typical Python app. Wait for "Deployment successful."

**Required app setting:** `SCM_DO_BUILD_DURING_DEPLOYMENT` must be `1`.
Set it in App Service → Environment variables if not already present.

---

## 4. sys.path Fix for Azure Oryx Extraction

**The problem:** Oryx compresses the build into `output.tar.zst` and
extracts it at startup to `/tmp/<random-hash>/`. Python's working
directory doesn't match, so relative imports fail:

```
ModuleNotFoundError: No module named 'config'
```

This happens even with a correctly structured zip if the working
directory isn't set to the app root.

**The fix:** Add this near the top of your entry point (e.g. `main.py`),
before any local imports:

```python
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
```

This is permanent and non-fragile — works regardless of which `/tmp/`
path Oryx extracts to. No impact on local development.

---

## 5. Startup Command

Set in Azure Portal → App Service → **Configuration** → **General
settings** → Startup command:

```
antenv/bin/python main.py
```

Or via CLI:

```powershell
az webapp config set `
  --resource-group <your-resource-group> `
  --name <your-app-service> `
  --startup-file "antenv/bin/python main.py"
```

Replace `main.py` with your entry point filename.

> **Don't use `python main.py`** — it may not find the Oryx-created
> virtual environment. `antenv/bin/python` ensures the correct Python
> with all installed dependencies.

---

## 6. App Gateway / APIM — Messaging Endpoint (Bot Framework)

**The problem:** If the App Service is behind an Application Gateway or
APIM, external services (Bot Service, Teams) can't reach it directly.
Hitting the App Service URL returns `403 Forbidden`, and "Test in Web
Chat" shows nothing — no errors, just silence.

**The fix:** The Bot Service messaging endpoint must point to the
**gateway's public URL**, not the App Service:

```
✅ https://<your-gateway-domain>/api/messages
❌ https://<your-app>.azurewebsites.net/api/messages
```

Set it in: **Bot Service → Configuration → Messaging endpoint**

**Gateway requirements for Bot Framework:**

1. **Routes `/api/messages`** to the backend App Service
2. **Valid CA-signed SSL certificate** — Bot Service rejects self-signed
3. **WAF allows Bot Framework POSTs** — allowlist `AzureBotService`
   service tag if a WAF is enabled
4. **Passes through auth headers** — `X-MS-CLIENT-PRINCIPAL` and
   `X-MS-CLIENT-PRINCIPAL-ID` must not be stripped (needed if your app
   uses Easy Auth for user-level access control)

> **Applies to any Azure Bot behind a gateway** — not just this project.

---

## 7. Cross-Subscription Resources

Azure Bot Service, Azure OpenAI, and Entra App Registrations can live
in a different subscription than the App Service. They connect over
HTTPS — subscription and resource group boundaries don't matter.

When moving to a new App Service in a different subscription, update:

1. **Bot Service → Messaging endpoint** → new gateway or App Service URL
2. **App Registration → Redirect URI** → new App Service URL (for Easy
   Auth callback: `https://<new-app>.azurewebsites.net/.auth/login/aad/callback`)

All other resources (OpenAI, Bot Service, App Registration) stay where
they are.

---

## 8. SCM Access Restrictions Blocking Deployment

**The problem:** If the App Service has access restrictions on the SCM
(Kudu) site, `az webapp deployment source config-zip` fails silently:

```
ConnectionResetError: [WinError 10054] An existing connection was
forcibly closed by the remote host
```

No useful error message — just a connection reset.

**The fix:** Temporarily add your IP to the SCM allow list:

```powershell
# Get your public IP
(Invoke-WebRequest -Uri ifconfig.me -UseBasicParsing).Content

# Add it (replace YOUR_IP, your-rg, your-app)
az webapp config access-restriction add `
  --resource-group <your-rg> --name <your-app> `
  --priority 20 --ip-address "YOUR_IP/32" `
  --rule-name DeployFromMyMachine --scm-site true

# After deploy, remove it
az webapp config access-restriction remove `
  --resource-group <your-rg> --name <your-app> `
  --rule-name DeployFromMyMachine --scm-site true
```

> **Always remove the rule after deploying.** The SCM console exposes
> app files, environment variables (including secrets), and a debug
> shell.

---

## 9. Teams Manifest — App ID Placeholder

**The problem:** Uploading the Teams app package fails with:

```
Manifest parsing error message unavailable.
```

**The cause:** The `manifest.json` still contains placeholder values
like `<your-app-id-from-entra>` instead of the actual Application
(client) ID from the Entra app registration.

**The fix:** Open `teams-app/manifest.json` and replace **every**
instance of `<your-app-id-from-entra>` with your actual app ID (a GUID
like `8b5129f2-7a67-4e55-a8fd-db8ad4032246`). It typically appears in
both the `id` field and the `bots[0].botId` field.

Then re-zip the three files (`manifest.json`, `outline.png`, `color.png`)
— files must be at the **root of the zip**, not inside a folder.

---

## 10. Dependency Version Conflicts (Pre-Release Packages)

**The problem:** Oryx build fails with a pip resolver conflict:

```
Cannot install package-a==1.0.0rc5 and package-b==1.0.0rc6
```

**The cause:** One package depends on a newer version of another, but
`requirements.txt` pins an older version.

**The fix:**
1. Check what versions are in your `wheels/` folder (if bundling private
   packages)
2. Update `requirements.txt` to match — all interdependent packages
   must have compatible version pins
3. Include `--pre` flag in `requirements.txt` if using pre-release
   versions
4. Include `--find-links wheels` if bundling private `.whl` files

---

## Quick Diagnosis Checklist

Run through these in order when something isn't working:

| Check | How | What to look for |
|-------|-----|------------------|
| Build ran? | Log stream or Kudu deploy log | >120s = good. <60s = pip install was skipped |
| requirements.txt found? | Search build log for "Could not find" | If found → zip structure wrong (#2) |
| App starts? | Log stream | HTTP `200` access logs = running |
| Import error? | Log stream | `ModuleNotFoundError` → backslash zip (#1) or sys.path (#4) |
| Bot connected? | "Test in Web Chat" | No response → messaging endpoint wrong (#6) |
| 403 on URL? | Browser → App Service URL | Behind gateway → use gateway URL (#6) |
| Deploy rejected? | CLI error `10054` | SCM access restriction blocking you (#8) |
| Teams upload fails? | "Manifest parsing error" | Placeholder app ID in manifest.json (#9) |
| Env vars set? | App Service → Environment variables | All required vars present |

---

## Copy-Paste Deployment Commands

```powershell
# ── 1. Create the zip (from inside your project folder) ──
cd C:\path\to\your-project
python -c "import zipfile, os; z=zipfile.ZipFile(r'C:\Temp\deploy.zip','w',zipfile.ZIP_DEFLATED); [z.write(os.path.join(r,f),os.path.join(r,f).replace(os.sep,'/')) for r,d,fs in os.walk('.') if '__pycache__' not in r for f in fs if not f.endswith('.pyc')]; z.close(); print('Done')"

# ── 2. Deploy ──
az webapp deployment source config-zip --resource-group <your-rg> --name <your-app> --src C:\Temp\deploy.zip

# ── 3. Set startup command (first deploy only) ──
az webapp config set --resource-group <your-rg> --name <your-app> --startup-file "antenv/bin/python main.py"

# ── 4. Restart ──
az webapp restart --resource-group <your-rg> --name <your-app>
```

---

## Alternative: GitHub-Based Deployment

To avoid the CLI/zip/Kudu chain entirely:

1. Push code to a GitHub repo
2. Azure Portal → App Service → **Deployment** → **Deployment Center**
3. Source: **GitHub** → select repo and branch
4. Click **Save** — Azure auto-deploys on every push

This bypasses the CLI, doesn't require SCM access from your machine,
and doesn't need IP whitelisting. Oryx build runs server-side.

---

*Last updated: 2026-04-06*
