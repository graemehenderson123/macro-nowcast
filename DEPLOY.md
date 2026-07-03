# Deploy to Streamlit Community Cloud

Everything is ready to push. Total: **5 steps, ~3 minutes**.

## 1 — Push this repo to GitHub

Run this from the machine where `~/macro-nowcast/` sits (or copy the folder
first):

```bash
cd ~/macro-nowcast

# a) create a private repo on GitHub (via the web UI or gh CLI)
#    – Name suggestion: macro-nowcast
#    – Visibility: Private
#    – Do NOT initialise with README/gitignore/licence — leave it empty

# b) push
git remote add origin https://github.com/<your-username>/macro-nowcast.git
git branch -M main
git push -u origin main
```

If you use SSH keys:

```bash
git remote add origin git@github.com:<your-username>/macro-nowcast.git
git push -u origin main
```

## 2 — Open Streamlit Community Cloud

Go to <https://share.streamlit.io/> and sign in with GitHub (approve the
Streamlit OAuth app if it asks — this is what lets it read your private
repos).

## 3 — Create a new app

Click **New app** → **Deploy a public app from GitHub** *(the label is
misleading — it works for private repos too if you're the owner)*.

Fill in:

| Field | Value |
|---|---|
| Repository | `<your-username>/macro-nowcast` |
| Branch | `main` |
| Main file path | `app/streamlit_app.py` |
| App URL | `macro-nowcast` (or whatever slug you like) |
| Python version | `3.11` |

## 4 — Add secrets

Click **Advanced settings** *before* clicking Deploy. In the **Secrets**
textarea paste (TOML format):

```toml
FRED_API_KEY = "paste_your_fred_key_here"
APP_PASSWORD = "nowcast-2026"
```

The FRED key is the one already in `~/.openclaw/workspace/.env` (find it with
`grep FRED_API_KEY ~/.openclaw/workspace/.env`). Change `APP_PASSWORD` to
whatever you like — this is what protects the URL.

## 5 — Deploy

Click **Deploy**. First build takes ~2 minutes while it installs
`streamlit + plotly + pandas + numpy + requests`. Watch the build log; when
it says **Your app is live!** you'll get a URL like:

```
https://macro-nowcast.streamlit.app
```

First visit will warm the FRED cache — takes ~15 seconds and you'll see a
spinner. After that every visit is instant until the 8-hour cache TTL expires
or you click **🔄 Force rebuild from FRED** in the sidebar.

## Verifying it works

- Visit the URL → password prompt appears
- Enter `APP_PASSWORD` → dashboard loads
- Regime card at top shows current label + G/I/L Z-scores
- Growth / Inflation / Liquidity sections each show:
  - Hard/Soft/HSS/Breadth stat cards
  - Composite Z line chart (hover shows exact value + date)
  - Top-5 movers table
  - Expandable "All components" with sortable table, sparklines per series,
    and raw-underlying-series charts
- Sidebar time range selector applies to all charts

## Updating later

Any push to `main` triggers an automatic redeploy. So the workflow is:

```bash
# edit files locally, then...
git commit -am "tweak thing"
git push
```

Streamlit picks it up within ~30 seconds.
