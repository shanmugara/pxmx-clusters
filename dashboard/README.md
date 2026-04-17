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

## Kubernetes Installation

Two options are provided: raw manifests or the Helm chart (recommended).

### Option A — Helm chart (recommended)

A Helm chart is available at [`deploy/helm/pxmx-dashboard/`](../deploy/helm/pxmx-dashboard/).

#### Prerequisites

- Helm 3.x (`brew install helm` or see [helm.sh](https://helm.sh/docs/intro/install/))
- A Kubernetes cluster with `kubectl` access

#### Install

```bash
helm install pxmx-dashboard deploy/helm/pxmx-dashboard \
  --namespace pxmx-dashboard \
  --create-namespace \
  --set github.token=ghp_your_token_here \
  --set github.repo=your-username/pxmx-clusters
```

#### Install with Ingress enabled

```bash
helm install pxmx-dashboard deploy/helm/pxmx-dashboard \
  --namespace pxmx-dashboard \
  --create-namespace \
  --set github.token=ghp_your_token_here \
  --set github.repo=your-username/pxmx-clusters \
  --set ingress.enabled=true \
  --set ingress.host=dashboard.example.com
```

#### Install using a values file (recommended for GitOps)

```bash
# Copy and edit the values file
cp deploy/helm/pxmx-dashboard/values.yaml my-values.yaml
# edit my-values.yaml — set github.repo, ingress.host, etc.
# Supply the token separately to avoid committing it:
helm install pxmx-dashboard deploy/helm/pxmx-dashboard \
  --namespace pxmx-dashboard \
  --create-namespace \
  -f my-values.yaml \
  --set github.token=ghp_your_token_here
```

#### Use an existing Secret (Sealed Secrets / External Secrets)

If you manage secrets externally, create a secret with key `github-token` and point the chart at it:

```bash
# Create your secret by other means, then:
helm install pxmx-dashboard deploy/helm/pxmx-dashboard \
  --namespace pxmx-dashboard \
  --create-namespace \
  --set github.existingSecret=my-existing-secret \
  --set github.repo=your-username/pxmx-clusters
```

#### Upgrade

```bash
helm upgrade pxmx-dashboard deploy/helm/pxmx-dashboard \
  --namespace pxmx-dashboard \
  --reuse-values \
  --set image.tag=v0.0.2
```

#### Uninstall

```bash
helm uninstall pxmx-dashboard --namespace pxmx-dashboard
```

#### Key values

| Value | Default | Description |
|---|---|---|
| `github.token` | `""` | GitHub PAT (required unless `github.existingSecret` is set) |
| `github.existingSecret` | `""` | Use a pre-existing Secret instead of creating one |
| `github.repo` | `shanmugara/pxmx-clusters` | Repository in `owner/repo` format |
| `github.ref` | `main` | Branch for workflow dispatches |
| `image.repository` | `shanmugara/pxmx-dashboard` | Container image |
| `image.tag` | _(appVersion)_ | Image tag; defaults to Chart appVersion |
| `ingress.enabled` | `false` | Enable the Ingress resource |
| `ingress.host` | `dashboard.example.com` | Hostname for the Ingress |
| `namespaceCreate` | `true` | Create the namespace; set `false` if it already exists |

---

### Option B — Raw manifests

Manifests for a production Kubernetes deployment are in [`deploy/k8s/`](../deploy/k8s/).

### Manifests overview

| File | What it creates |
|---|---|
| `namespace.yaml` | `pxmx-dashboard` namespace |
| `secret.yaml` | `dashboard-secret` — holds `GITHUB_TOKEN` |
| `configmap.yaml` | `dashboard-config` — non-sensitive env vars (`GITHUB_REPO`, `PORT`, etc.) |
| `deployment.yaml` | Single-replica Deployment running the Gunicorn container |
| `service.yaml` | ClusterIP Service on port 80 → container port 5001 |
| `ingress.yaml` | Optional Ingress (commented out; nginx + cert-manager example) |

### 1. Build and push the image

```bash
# From the repo root (build context must be the root so example-cluster.yaml is available)
docker build -f dashboard/Dockerfile -t ghcr.io/<owner>/pxmx-dashboard:latest .
docker push ghcr.io/<owner>/pxmx-dashboard:latest
```

Update the `image:` field in `deploy/k8s/deployment.yaml` to match your registry path.

### 2. Apply the namespace

```bash
kubectl apply -f deploy/k8s/namespace.yaml
```

### 3. Create the GitHub token secret

Never commit a token in plain text. Create the secret directly with `kubectl`:

```bash
kubectl create secret generic dashboard-secret \
  --namespace pxmx-dashboard \
  --from-literal=github-token=ghp_your_token_here \
  --dry-run=client -o yaml | kubectl apply -f -
```

### 4. Adjust the ConfigMap (optional)

Edit `deploy/k8s/configmap.yaml` to set your `GITHUB_REPO` and any other tunables, then apply:

```bash
kubectl apply -f deploy/k8s/configmap.yaml
```

### 5. Deploy

```bash
kubectl apply -f deploy/k8s/deployment.yaml
kubectl apply -f deploy/k8s/service.yaml
```

Or apply everything at once (the secret step above must already be done):

```bash
kubectl apply -f deploy/k8s/
```

Verify the pod comes up:

```bash
kubectl -n pxmx-dashboard get pods
kubectl -n pxmx-dashboard logs -l app.kubernetes.io/name=pxmx-dashboard -f
```

### 6. Expose via Ingress (optional)

Uncomment and edit `deploy/k8s/ingress.yaml`, replacing `dashboard.example.com` with your hostname, then:

```bash
kubectl apply -f deploy/k8s/ingress.yaml
```

Without an Ingress you can reach the dashboard via port-forward for testing:

```bash
kubectl -n pxmx-dashboard port-forward svc/pxmx-dashboard 8080:80
# open http://localhost:8080
```

### Updating the deployment

```bash
# After rebuilding and pushing a new image:
kubectl -n pxmx-dashboard rollout restart deployment/pxmx-dashboard
kubectl -n pxmx-dashboard rollout status  deployment/pxmx-dashboard
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
