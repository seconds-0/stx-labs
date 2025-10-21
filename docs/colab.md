# Google Colab Workflow

## Overview
- Supports running `notebooks/stx_pox_flywheel.ipynb` directly in Colab, installing repo dependencies, and managing secrets via the Colab Secrets API.
- Fits both ad-hoc analysis and reproducible sharing by combining GitHub-hosted notebooks with Colab’s hosted runtime.

## Launching the Notebook
- Public repos can be opened with  
  `https://colab.research.google.com/github/<org>/<repo>/blob/<branch>/notebooks/stx_pox_flywheel.ipynb`.  
  Example (current repo):  
  `https://colab.research.google.com/github/seconds-0/stx-labs/blob/main/notebooks/stx_pox_flywheel.ipynb`. citeturn0search1
- Optional CLI: `colab-cli open-nb notebooks/stx_pox_flywheel.ipynb` opens the local file in Colab and syncs a Drive copy for future sessions. citeturn0search0
- **Private repo note:** direct links prompt a GitHub authorization dialog. In Colab, use `File → Open notebook → GitHub`, sign in, and paste `seconds-0/stx-labs` to list notebooks. Authorize with a GitHub PAT that includes `repo` scope when prompted.

## Install Project Dependencies
```python
!pip install -r https://raw.githubusercontent.com/<org>/<repo>/main/requirements.txt
```
Example for this project:  
`!pip install -r https://raw.githubusercontent.com/seconds-0/stx-labs/main/requirements.txt`  
Avoid committing Colab’s ephemeral `pip` installs; the notebook documents required packages.

## Secrets & Environment
1. In Colab, click the key icon (left sidebar) → “Add new secret”. Store `HIRO_API_KEY` and any other credentials. citeturn0search8
2. Retrieve secrets inside the notebook:
```python
import os
from google.colab import userdata

os.environ["HIRO_API_KEY"] = userdata.get("HIRO_API_KEY")
```
This mirrors the local `.env` workflow so `src.config` and downstream helpers work unchanged. citeturn0search11

## Syncing with GitHub
- From Colab: **File → Save a copy in GitHub** (requires PAT with `repo` scope).
- From CLI:  
  1. `pip install colab-cli`  
  2. Generate Google Drive OAuth credentials and run `colab-cli set-config client_secrets.json`.  
  3. Select the Google account `colab-cli set-auth-user <index>`.  
  4. Use `colab-cli pull-nb` / `push-nb` to sync notebooks with Drive before committing to Git. citeturn0search0
- Keep notebooks versioned in Git; treat Drive as the transient buffer between Colab and the repo.

## Recommended Workflow
1. Open notebook via direct link or CLI.
2. Install dependencies (first cell) and load secrets.
3. Run data pulls, verify outputs, and ensure artifacts land in `/content/out/` if exporting.
4. `colab-cli pull-nb` to fetch Colab edits locally, run `pytest`, and push commits.
5. Regenerate `Open in Colab` links as needed (the link pattern is deterministic, or use a generator CLI such as `github-to-colab-link`). citeturn0search2
