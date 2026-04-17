# pxmx-clusters Dashboard

A lightweight Flask web app that proxies the GitHub Actions API and displays real-time Terraform run progress for each cluster defined in this repository.

---

## How It Works

```
Browser (auto-refreshes every 10 s)
        ↓  GET /api/clusters
    Flask app (app.py)
        ↓  GitHub Actions REST API
    Workflow runs for cluster-apply.yml
    Workflow runs for cluster-destroy.yml
        ↓
    Per-job step statuses
        ↓
    Progress percentage + current step label
        ↓  JSON
    index.html renders cards per cluster
```

### Key Components

| File | Purpose |
|---|---|
| `app.py` | Flask server — fetches/caches GitHub API data, computes progress |
| `templates/index.html` | Single-page UI — auto-polls `/api/clusters` and renders cards |
| `requirements.txt` | Python dependencies (`flask`, `requests`) |

### Progress Mapping

`app.py` maps each Terraform workflow step to a progress percentage:

| Step | Start % | Done % |
|---|---|---|
| Set home | 2 | 5 |
| Generate tfvars | 8 | 14 |
| Configure git | 15 | 20 |
| Terraform init | 22 | 38 |
| Terraform plan | 40 | 68 |
| Terraform apply | 70 | 100 |

While `terraform apply` is running, the bar advances gradually from 70 % → 99 % over an assumed 5-minute window, so the bar never stalls.

### Caching

To avoid hammering the GitHub API, responses are cached in-process:
- Active (queued / in-progress) runs: **15-second TTL**
- Completed runs: **10-minute TTL** (they never change)

---

## Production Installation (systemd)

`install.sh` deploys the dashboard as a hardened systemd service running under a dedicated `pxmx` service account on any Linux host with Python 3 and `rsync`.

### 1. Copy the dashboard source to the target host

```bash
rsync -av dashboard/ user@yourhost:/tmp/pxmx-dashboard-src/
```

### 2. Run the installer as root

```bash
ssh user@yourhost
sudo bash /tmp/pxmx-dashboard-src/install.sh
```

The script:
- Creates the `pxmx` system user (no login shell, no home dir)
- Copies app files to `/opt/pxmx-dashboard`
- Creates a Python virtualenv and installs all dependencies
- Places an env file template at `/etc/pxmx-dashboard/env` (mode `640`, readable only by root and the `pxmx` group)
- Installs and enables `pxmx-dashboard.service` via systemd

### 3. Set secrets

```bash
sudo vi /etc/pxmx-dashboard/env
```

At minimum, set:

```ini
GITHUB_TOKEN=ghp_your_token_here
GITHUB_REPO=your-username/pxmx-clusters
```

### 4. Start the service

```bash
sudo systemctl start pxmx-dashboard
sudo systemctl status pxmx-dashboard
```

### 5. View logs

```bash
sudo journalctl -u pxmx-dashboard -f
```

### Re-deploying after code changes

Re-run the installer — it is idempotent and will sync new files, upgrade dependencies, and restart the service:

```bash
sudo bash /tmp/pxmx-dashboard-src/install.sh
```

### Useful service commands

```bash
sudo systemctl stop    pxmx-dashboard
sudo systemctl restart pxmx-dashboard
sudo systemctl disable pxmx-dashboard   # prevent start at boot
```

---

## Running Locally for Testing

### 1. Install dependencies

```bash
cd dashboard
pip install -r requirements.txt
```

> Use a virtual environment to keep things clean:
> ```bash
> python3 -m venv .venv && source .venv/bin/activate
> pip install -r requirements.txt
> ```

### 2. Create a GitHub Personal Access Token

The app needs read access to Actions. In GitHub:

1. Go to **Settings → Developer settings → Personal access tokens → Fine-grained tokens**
2. Grant **Read-only** access to **Actions** (and **Contents** if the repo is private)
3. Copy the token

### 3. Set environment variables

```bash
export GITHUB_TOKEN="github_pat_xxxxxxxxxxxx"
export GITHUB_REPO="your-username/pxmx-clusters"
# Optional — defaults to 5001
export PORT=5001
```

### 4. Start the server

```bash
python app.py
```

Expected output:
```
 * Running on http://0.0.0.0:5001
```

### 5. Open the dashboard

```
http://localhost:5001
```

The UI polls `/api/clusters` every 10 seconds. Active runs show an animated progress bar; completed runs show green (success) or red (failure).

---

## API Endpoint

### `GET /api/clusters`

Returns a JSON array of the most recent run entry per cluster per workflow type.

**Example response:**
```json
[
  {
    "cluster": "app1-cluster",
    "workflow": "apply",
    "status": "in_progress",
    "conclusion": null,
    "percent": 68,
    "current_step": "Terraform plan",
    "duration": "1m 42s",
    "run_url": "https://github.com/owner/pxmx-clusters/actions/runs/12345678",
    "created_at": "2026-03-17T10:00:00Z",
    "run_id": 12345678
  }
]
```

You can hit this endpoint directly with `curl` to verify the app is reading data correctly:

```bash
curl -s http://localhost:5001/api/clusters | python3 -m json.tool
```

---

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Cards show "No clusters found" | No workflow runs exist yet, or `GITHUB_REPO` is wrong |
| `{"error": "GITHUB_REPO env var is not set"}` | `GITHUB_REPO` env var missing |
| HTTP 401 from GitHub | `GITHUB_TOKEN` is missing, expired, or lacks Actions read permission |
| Progress bar stuck at 0 % | Job is queued but runner hasn't picked it up yet |
| Port already in use | Change `PORT` — e.g. `export PORT=8080` |
