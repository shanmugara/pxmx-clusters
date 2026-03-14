# pxmx-clusters

GitOps-driven Proxmox VM provisioning. Define clusters as YAML manifests, push to GitHub, and Terraform automatically builds your VMs in your home lab — no manual intervention required.

---

## How It Works

### Architecture Overview

```
You: edit clusters/<name>.yaml  →  git push
                                        ↓
                              GitHub detects push
                              queues Actions job
                                        ↓
                    Home lab runner (polls GitHub via HTTPS)
                    picks up the job and executes locally:
                                        ↓
                        python3 scripts/yaml_to_tfvars.py
                                        ↓
                        terraform init  (MinIO backend)
                        terraform plan
                        terraform apply
                                        ↓
                        Proxmox API (192.168.x.x:8006)
                                        ↓
                            VMs created on Proxmox
                            DNS + DHCP registered
```

**Nothing is exposed to the internet.** The self-hosted runner reaches out to GitHub over HTTPS (port 443); GitHub never reaches into your network.

---

## Repository Structure

```
clusters/                        # One YAML file per cluster
    example-cluster.yaml
scripts/
    yaml_to_tfvars.py            # Converts cluster YAML → Terraform tfvars
terraform/
    backend.tf                   # S3/MinIO remote state backend
    main.tf                      # VM module calls
    providers.tf
    variables.tf
.github/workflows/
    cluster-apply.yml            # Triggered on push/PR to main
    cluster-destroy.yml          # Manually triggered only
```

---

## Defining a Cluster

Copy the example and edit it:

```bash
cp clusters/example-cluster.yaml clusters/my-cluster.yaml
```

```yaml
apiVersion: v1
kind: Cluster
metadata:
  name: my-cluster
  description: "My cluster description"
spec:
  node_prefix: myvm        # VMs will be named myvm-1, myvm-2, etc.
  node_count: 3

  # Proxmox settings
  target_node: omegakvm002
  template: ubuntu-24.04-cloud-init-template
  bridge: vmbr0

  # VM resources
  cores: 4
  memory: 8192
  disk_size: "40G"

  # DNS settings
  dns_zone: "yourdomain.net."
  dns_ttl: 300
```

Push to `main` and the automation handles the rest.

**One repo serves all clusters.** Each cluster is a separate YAML file. State is isolated per cluster in MinIO, so they never interfere with each other.

---

## Workflows

### cluster-apply (automatic)

Triggered by:
- **Push to `main`** with changes under `clusters/**/*.yaml` → full apply
- **Pull request to `main`** with those same changes → plan only, plan saved as artifact

Steps:
1. **Detect** — diffs `HEAD~1..HEAD`, finds changed YAML files, fans out into a matrix (one Terraform run per changed cluster)
2. **Generate tfvars** — `yaml_to_tfvars.py` converts the cluster YAML to `terraform/generated.auto.tfvars`
3. **Terraform Init** — initialises against the per-cluster state in MinIO (`clusters/<name>/terraform.tfstate`)
4. **Terraform Plan** — always runs; on PRs the plan is uploaded as a workflow artifact
5. **Terraform Apply** — runs only on push to `main`, not on PRs

### cluster-destroy (manual only)

Triggered manually from the GitHub Actions UI (Actions tab → Cluster Destroy → Run workflow).

Inputs required:
- `cluster` — name of the cluster (must match `clusters/<name>.yaml`)
- `confirm` — type the cluster name again to confirm

The job **only runs if both inputs match** — mistype either and it is skipped entirely.

Steps:
1. Validates the cluster YAML exists
2. Generates tfvars
3. Terraform init against the cluster's state
4. `terraform destroy -auto-approve`
5. On success, auto-commits the removal of `clusters/<name>.yaml` from the repo

---

## Self-Hosted Runner Setup

The workflows use `runs-on: [self-hosted, proxmox]`, meaning jobs run on a runner agent **you install in your home lab** — not on GitHub's cloud. This gives Terraform direct access to your Proxmox API and MinIO instance without exposing anything to the internet.

### 1. Prepare a machine in your lab

A small VM or LXC container on Proxmox works well. It needs:
- Network access to your Proxmox API (e.g. `https://192.168.x.x:8006`)
- Network access to your MinIO instance
- Outbound HTTPS (port 443) access to GitHub
- `python3`, `pip`, and `terraform` installed

Install dependencies:
```bash
# Python YAML library
pip3 install pyyaml

# Terraform (Debian/Ubuntu example)
wget -O- https://apt.releases.hashicorp.com/gpg | sudo gpg --dearmor -o /usr/share/keyrings/hashicorp-archive-keyring.gpg
echo "deb [signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] https://apt.releases.hashicorp.com $(lsb_release -cs) main" | sudo tee /etc/apt/sources.list.d/hashicorp.list
sudo apt update && sudo apt install terraform
```

### 2. Register the runner with GitHub

In your GitHub repo: **Settings → Actions → Runners → New self-hosted runner**

GitHub will show you a set of commands. Run them on your lab machine:

```bash
mkdir -p ~/actions-runner && cd ~/actions-runner

# Download (get the exact URL from the GitHub UI — it includes the current version)
curl -o actions-runner-linux-x64.tar.gz -L https://github.com/actions/runner/releases/download/vX.X.X/actions-runner-linux-x64-X.X.X.tar.gz
tar xzf actions-runner-linux-x64.tar.gz

# Register — token comes from the GitHub UI, expires after 1 hour
./config.sh --url https://github.com/YOUR_ORG/pxmx-clusters \
            --token YOUR_REGISTRATION_TOKEN \
            --labels self-hosted,proxmox \
            --name my-proxmox-runner
```

### 3. Install as a system service (so it survives reboots)

```bash
sudo ./svc.sh install
sudo ./svc.sh start

# Verify it is running
sudo ./svc.sh status
```

The runner will appear as **Online** in GitHub → Settings → Actions → Runners.

---

## First-Time GitHub Setup

After pushing this repo to GitHub, complete these steps before workflows will run:

### 1. Enable Actions
**Settings → Actions → General → "Allow all actions and reusable workflows"** → Save

### 2. Add Secrets
**Settings → Secrets and variables → Actions → New repository secret**

Add all secrets listed in the [GitHub Secrets](#github-secrets) section below.

### 3. Register a self-hosted runner
**Settings → Actions → Runners → New self-hosted runner**

Select Linux, run the commands GitHub provides on your lab machine. When prompted for labels, ensure both `self-hosted` and `proxmox` are included. Then install as a service:
```bash
sudo ./svc.sh install && sudo ./svc.sh start
```
The runner will appear as **Online** in Settings → Actions → Runners once connected.

### 4. Create the MinIO state bucket
Before the first workflow run, ensure the `terraform-state` bucket exists in MinIO — `terraform init` will fail without it:
```bash
mc alias set minio https://minio.yourdomain.net ACCESS_KEY SECRET_KEY
mc mb minio/terraform-state
```

Once the runner is online and secrets are set, push any change to a `clusters/*.yaml` file and the `cluster-apply` workflow will trigger automatically.

---

## GitHub Secrets

The following secrets must be set in your GitHub repo (**Settings → Secrets and variables → Actions**):

| Secret | Description |
|---|---|
| `PM_API_URL` | Proxmox API URL, e.g. `https://192.168.1.10:8006/api2/json` |
| `PM_USER` | Proxmox API user, e.g. `terraform@pve` |
| `PM_PASSWORD` | Proxmox API password or token secret |
| `CI_PASSWORD` | Cloud-init user password for created VMs |
| `DNS_KEY_SECRET` | TSIG key secret for dynamic DNS updates |
| `MINIO_ENDPOINT` | MinIO endpoint URL, e.g. `https://minio.yourdomain.net` |
| `MINIO_ACCESS_KEY` | MinIO access key |
| `MINIO_SECRET_KEY` | MinIO secret key |

Secrets are injected into Terraform as `TF_VAR_*` environment variables at runtime — they are never stored in code or state files.

---

## MinIO (Terraform State Backend)

Terraform state is stored remotely in MinIO (S3-compatible). Each cluster gets its own isolated state file:

```
terraform-state/
    clusters/
        my-cluster/terraform.tfstate
        prod-cluster/terraform.tfstate
        dev-cluster/terraform.tfstate
```

Create the bucket in MinIO before running for the first time:
```bash
mc alias set minio https://minio.yourdomain.net ACCESS_KEY SECRET_KEY
mc mb minio/terraform-state
```

---

## Terraform Module

`terraform/main.tf` calls the reusable VM module from `pxmx-template`:

```hcl
module "vm" {
  source   = "git::https://github.com/shanmugara/pxmx-template.git//modules/vm?ref=main"
  for_each = toset([for i in range(var.vm_qty) : "${var.vm_prefix}-${i + 1}"])
  ...
}
```

It creates `vm_qty` VMs named `<prefix>-1`, `<prefix>-2`, etc. and registers them with DNS and optionally Kea DHCP.

Outputs:
```hcl
output "vm_details" {
  # name, vm_id, ip, fqdn for each created VM
}
```

---

## Day-to-Day Usage

| Task | Action |
|---|---|
| Create a new cluster | Add `clusters/<name>.yaml`, push to `main` |
| Modify a cluster | Edit `clusters/<name>.yaml`, push to `main` |
| Preview changes before applying | Open a PR — plan runs but apply does not |
| Destroy a cluster | GitHub Actions UI → Cluster Destroy → enter cluster name twice |
| Add more VMs to a cluster | Increase `node_count` in the YAML, push to `main` |
