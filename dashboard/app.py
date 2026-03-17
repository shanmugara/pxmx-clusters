#!/usr/bin/env python3
"""
pxmx-clusters Dashboard
Proxies the GitHub Actions API to display per-cluster Terraform run progress.

Required environment variables:
  GITHUB_TOKEN  - GitHub personal access token (repo + actions:read scope)
  GITHUB_REPO   - "owner/repo" e.g.  shanmugara/pxmx-clusters

Optional:
  PORT          - HTTP port to listen on (default: 5001)
"""

import os
import re
import time
import base64
from datetime import datetime, timezone

import requests
import yaml
from flask import Flask, jsonify, render_template, request

# ── Configuration ─────────────────────────────────────────────────────────────
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO  = os.environ.get("GITHUB_REPO", "")   # "owner/repo"
API_BASE     = "https://api.github.com"

APPLY_WORKFLOW   = "cluster-apply.yml"
DESTROY_WORKFLOW = "cluster-destroy.yml"
GITHUB_REF       = os.environ.get("GITHUB_REF", "main")  # branch to dispatch against

# Path to the example cluster template (relative to this file's parent directory)
_TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "..", "example-cluster.yaml")

def _load_template() -> str:
    try:
        with open(_TEMPLATE_PATH) as f:
            return f.read()
    except OSError:
        return ""

CLUSTER_TEMPLATE = _load_template()

# Allowed characters in a cluster name (matches file-system / k8s name conventions)
_CLUSTER_NAME_RE = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9_-]{0,62}$')

# How many recent workflow runs to inspect per workflow file
RUNS_PER_PAGE = 15

# ── Step-to-progress mapping ───────────────────────────────────────────────────
# Substring of step name (lowercase) → percent reached when that step COMPLETES
# Keys shared between apply and destroy workflows are safe because each workflow
# only contains the relevant subset of steps.
STEP_DONE_PCT: dict[str, int] = {
    # --- shared ---
    "set home":                    5,
    "generate tfvars":            15,
    "configure git":              22,
    "terraform init":             38,
    # --- apply-only ---
    "terraform plan":             68,
    "terraform apply":            95,
    "upload plan":               100,   # PR only — runs after apply is skipped
    # --- destroy-only ---
    "validate cluster":           10,
    "terraform destroy":          95,
    "remove cluster manifest":   100,
}

# Percent shown the moment a step becomes in_progress
STEP_START_PCT: dict[str, int] = {
    # --- shared ---
    "set home":                    2,
    "generate tfvars":             8,
    "configure git":              16,
    "terraform init":             24,
    # --- apply-only ---
    "terraform plan":             40,
    "terraform apply":            70,
    "upload plan":                96,   # PR only
    # --- destroy-only ---
    "validate cluster":            6,
    "terraform destroy":           50,
    "remove cluster manifest":     96,
}

# Assumed max seconds for the long-running Terraform step (live sub-progress)
APPLY_ESTIMATED_SECONDS   = 300  # 5 minutes
DESTROY_ESTIMATED_SECONDS = 300  # 5 minutes

# ── Simple in-process TTL cache (avoids hammering GitHub API) ─────────────────
_cache: dict[str, tuple[float, object]] = {}

def _cached_get(url: str, params: dict | None = None, ttl: int = 30, force: bool = False) -> dict:
    key = url + str(sorted((params or {}).items()))
    now = time.monotonic()
    if not force and key in _cache and now - _cache[key][0] < ttl:
        return _cache[key][1]
    result = _gh_get(url, params)
    _cache[key] = (now, result)
    return result


# ── GitHub API helpers ─────────────────────────────────────────────────────────
def _headers() -> dict:
    h = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if GITHUB_TOKEN:
        h["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return h


def _gh_get(url: str, params: dict | None = None) -> dict:
    try:
        resp = requests.get(url, headers=_headers(), params=params or {}, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException:
        return {}


def get_runs(workflow_file: str) -> list:
    data = _cached_get(
        f"{API_BASE}/repos/{GITHUB_REPO}/actions/workflows/{workflow_file}/runs",
        {"per_page": RUNS_PER_PAGE},
        ttl=20,
    )
    return data.get("workflow_runs", [])


def get_jobs(run_id: int, is_active: bool) -> list:
    # Active (in_progress/queued) runs: refresh every 15 s
    # Completed runs: cache for 10 min (they never change)
    ttl = 15 if is_active else 600
    url = f"{API_BASE}/repos/{GITHUB_REPO}/actions/runs/{run_id}/jobs"
    params = {"per_page": 100}
    data = _cached_get(url, params, ttl=ttl)
    jobs = data.get("jobs", [])
    # If the run is now complete but cached job data still shows in_progress
    # or queued (fetched while the runner was still active), the stale value
    # could be locked in the cache for up to 10 minutes. Force a fresh fetch
    # so the final status is reflected on the very next poll.
    if not is_active and any(j.get("status") in ("in_progress", "queued") for j in jobs):
        data = _cached_get(url, params, ttl=ttl, force=True)
        jobs = data.get("jobs", [])
    return jobs


# ── Progress computation ───────────────────────────────────────────────────────
def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def compute_progress(steps: list) -> tuple[int, str]:
    """Return (percent, current_step_name) based on GitHub step statuses."""
    pct = 0
    current = "Starting…"

    for step in steps:
        n = step["name"].lower()
        # Skip automatic setup/teardown steps
        if "set up job" in n or "complete job" in n or n.startswith("post "):
            continue

        if step["status"] == "in_progress":
            current = step["name"]
            for key, p in STEP_START_PCT.items():
                if key in n:
                    # For long-running terraform steps, gradually advance the
                    # bar so it doesn't stall while waiting for completion.
                    if "terraform apply" in n or "terraform destroy" in n:
                        estimated = (
                            DESTROY_ESTIMATED_SECONDS
                            if "terraform destroy" in n
                            else APPLY_ESTIMATED_SECONDS
                        )
                        started = _parse_dt(step.get("started_at"))
                        if started:
                            elapsed_s = (datetime.now(timezone.utc) - started).total_seconds()
                            # advance up to 44 points (50→94 for destroy, 70→99 for apply)
                            headroom = 44
                            sub = min(headroom, int(elapsed_s / estimated * headroom))
                            return p + sub, current
                    return max(pct, p), current
            # Step running but not in our map — stay at current pct
            return max(pct, 1), current

        if step["status"] == "completed" and step.get("conclusion") == "success":
            current = step["name"]
            for key, p in STEP_DONE_PCT.items():
                if key in n:
                    pct = max(pct, p)
        # skipped steps are intentionally not run — don't advance the bar

    return pct, current


def elapsed_str(started_at: str | None, completed_at: str | None = None) -> str:
    if not started_at:
        return ""
    start = _parse_dt(started_at)
    end   = _parse_dt(completed_at) or datetime.now(timezone.utc)
    if not start:
        return ""
    secs = max(0, int((end - start).total_seconds()))
    m, s = divmod(secs, 60)
    return f"{m}m {s:02d}s" if m else f"{s}s"


# ── Cluster name extraction ────────────────────────────────────────────────────
_JOB_RE = re.compile(r"terraform\s*\(([^)]+)\)", re.IGNORECASE)

def cluster_from_job(name: str) -> str | None:
    """'terraform (app1-cluster)' → 'app1-cluster'"""
    m = _JOB_RE.search(name)
    return m.group(1).strip() if m else None


# ── Main API route ─────────────────────────────────────────────────────────────
app = Flask(__name__)


@app.route("/api/clusters")
def api_clusters():
    if not GITHUB_REPO:
        return jsonify({"error": "GITHUB_REPO env var is not set"}), 500

    seen: dict[str, dict] = {}   # key = "cluster:workflow_type" → best entry

    for wf_file in [APPLY_WORKFLOW, DESTROY_WORKFLOW]:
        wf_type = "apply" if "apply" in wf_file else "destroy"

        for run in get_runs(wf_file):
            run_id         = run["id"]
            run_status     = run["status"]       # queued | in_progress | completed
            run_conclusion = run["conclusion"]   # success | failure | cancelled | None
            run_url        = run["html_url"]
            run_created    = run["created_at"]

            is_active = run_status in ("queued", "in_progress")
            jobs = get_jobs(run_id, is_active)

            for job in jobs:
                cluster = cluster_from_job(job["name"])
                if not cluster:
                    continue

                job_status     = job["status"]
                job_conclusion = job["conclusion"]
                steps          = job.get("steps", [])

                # ── Calculate percent + current step ──
                if job_status == "completed":
                    if job_conclusion == "success":
                        verb = "Apply" if wf_type == "apply" else "Destroy"
                        pct, current_step = 100, f"{verb} completed — SUCCESS"
                    elif job_conclusion in ("failure", "timed_out"):
                        pct, _ = compute_progress(steps)
                        failed = next(
                            (s["name"] for s in steps if s.get("conclusion") == "failure"),
                            "Unknown step",
                        )
                        current_step = f"Failed at: {failed}"
                    else:
                        pct, current_step = 0, "Cancelled"
                elif job_status == "in_progress":
                    pct, current_step = compute_progress(steps)
                else:
                    pct, current_step = 0, "Queued"

                entry = {
                    "cluster":      cluster,
                    "workflow":     wf_type,
                    "status":       job_status,
                    "conclusion":   job_conclusion,
                    "percent":      pct,
                    "current_step": current_step,
                    "duration":     elapsed_str(job.get("started_at"), job.get("completed_at")),
                    "run_url":      run_url,
                    "created_at":   run_created,
                    "run_id":       run_id,
                }

                key  = f"{cluster}:{wf_type}"
                prev = seen.get(key)

                # Keep this entry if: no previous, or this is in_progress and
                # previous was not, or same status but this run is newer.
                if (
                    not prev
                    or (job_status == "in_progress" and prev["status"] != "in_progress")
                    or (job_status == prev["status"] and run_created > prev["created_at"])
                ):
                    seen[key] = entry

    # ── Post-process: hide stale apply cards for destroyed clusters ──────────
    # If the most recent destroy run for a cluster succeeded (or is active) and
    # is newer than the most recent apply run, remove the apply card — the
    # cluster no longer exists and showing both would be confusing.
    filtered = {}
    for key, entry in seen.items():
        cluster  = entry["cluster"]
        wf_type  = entry["workflow"]
        destroy_entry = seen.get(f"{cluster}:destroy")

        if wf_type == "apply" and destroy_entry:
            destroy_active    = destroy_entry["status"] in ("queued", "in_progress")
            destroy_succeeded = destroy_entry["conclusion"] == "success"
            destroy_newer     = destroy_entry["created_at"] >= entry["created_at"]
            if destroy_newer and (destroy_succeeded or destroy_active):
                # Drop the apply card; only the destroy card will be shown
                continue

        filtered[key] = entry

    results = sorted(filtered.values(), key=lambda x: x["created_at"], reverse=True)
    return jsonify(results)


@app.route("/api/cleanup-destroyed", methods=["POST"])
def api_cleanup_destroyed():
    """
    Delete ALL GitHub Actions workflow runs (apply + destroy) for clusters
    whose most recent destroy run completed successfully.

    Requires the GITHUB_TOKEN to have actions:write (or repo) scope.
    Returns a summary of deleted run IDs.
    """
    if not GITHUB_TOKEN:
        return jsonify({"error": "GITHUB_TOKEN env var is not set"}), 500
    if not GITHUB_REPO:
        return jsonify({"error": "GITHUB_REPO env var is not set"}), 500

    # ── Step 1: identify "destroyed" clusters (same logic as api_clusters) ──
    # We need the full per-workflow-type best entry to determine which clusters
    # have a successful destroy as their most recent run.
    seen_best: dict[str, dict] = {}  # key = "cluster:wf_type" → best entry

    # Collect ALL run IDs per cluster across both workflows for bulk deletion
    all_run_ids_by_cluster: dict[str, set[int]] = {}  # cluster → set of run_ids

    for wf_file in [APPLY_WORKFLOW, DESTROY_WORKFLOW]:
        wf_type = "apply" if "apply" in wf_file else "destroy"
        for run in get_runs(wf_file):
            run_id      = run["id"]
            run_status  = run["status"]
            run_created = run["created_at"]
            is_active   = run_status in ("queued", "in_progress")
            jobs        = get_jobs(run_id, is_active)
            for job in jobs:
                cluster = cluster_from_job(job["name"])
                if not cluster:
                    continue
                # Track every run_id we've seen for this cluster
                all_run_ids_by_cluster.setdefault(cluster, set()).add(run_id)
                # Also track the best entry per key (for destroyed-cluster detection)
                job_status     = job["status"]
                job_conclusion = job["conclusion"]
                entry = {
                    "cluster":    cluster,
                    "workflow":   wf_type,
                    "status":     job_status,
                    "conclusion": job_conclusion,
                    "created_at": run_created,
                    "run_id":     run_id,
                }
                key  = f"{cluster}:{wf_type}"
                prev = seen_best.get(key)
                if (
                    not prev
                    or (job_status == "in_progress" and prev["status"] != "in_progress")
                    or (job_status == prev["status"] and run_created > prev["created_at"])
                ):
                    seen_best[key] = entry

    # ── Step 2: find clusters whose best destroy run succeeded ───────────────
    destroyed_clusters: set[str] = set()
    for key, entry in seen_best.items():
        if entry["workflow"] != "destroy" or entry["conclusion"] != "success":
            continue
        cluster = entry["cluster"]
        apply_entry = seen_best.get(f"{cluster}:apply")
        # Only clean up if destroy is newer than the apply (or no apply exists)
        if not apply_entry or entry["created_at"] >= apply_entry["created_at"]:
            destroyed_clusters.add(cluster)

    if not destroyed_clusters:
        return jsonify({"ok": True, "deleted": [], "message": "No destroyed clusters to clean up."})

    # ── Step 3: delete all workflow runs for those clusters ──────────────────
    deleted: list[int] = []
    errors:  list[str] = []

    for cluster in destroyed_clusters:
        for run_id in all_run_ids_by_cluster.get(cluster, set()):
            url = f"{API_BASE}/repos/{GITHUB_REPO}/actions/runs/{run_id}"
            try:
                resp = requests.delete(url, headers=_headers(), timeout=10)
                if resp.status_code == 204:
                    deleted.append(run_id)
                    # Evict any cache entries referencing this run
                    keys_to_drop = [k for k in _cache if str(run_id) in k]
                    for k in keys_to_drop:
                        _cache.pop(k, None)
                else:
                    errors.append(f"run {run_id}: HTTP {resp.status_code}")
            except requests.RequestException as exc:
                errors.append(f"run {run_id}: {exc}")

    # Also bust the runs-list cache so the next poll sees empty history
    runs_cache_keys = [k for k in _cache if "/actions/workflows/" in k and "/runs" in k]
    for k in runs_cache_keys:
        _cache.pop(k, None)

    return jsonify({
        "ok":      len(errors) == 0,
        "deleted": deleted,
        "clusters": sorted(destroyed_clusters),
        "errors":  errors,
    })


@app.route("/api/destroy/<cluster>", methods=["POST"])
def api_destroy(cluster: str):
    """Trigger the cluster-destroy workflow via workflow_dispatch."""
    if not GITHUB_TOKEN:
        return jsonify({"error": "GITHUB_TOKEN env var is not set"}), 500
    if not GITHUB_REPO:
        return jsonify({"error": "GITHUB_REPO env var is not set"}), 500
    if not _CLUSTER_NAME_RE.match(cluster):
        return jsonify({"error": "Invalid cluster name"}), 400

    url = f"{API_BASE}/repos/{GITHUB_REPO}/actions/workflows/{DESTROY_WORKFLOW}/dispatches"
    try:
        resp = requests.post(
            url,
            headers=_headers(),
            json={
                "ref": GITHUB_REF,
                "inputs": {
                    "cluster": cluster,
                    "confirm": cluster,  # workflow guards on cluster == confirm
                },
            },
            timeout=10,
        )
        if resp.status_code == 204:
            return jsonify({"ok": True})
        return jsonify({"error": f"GitHub API returned {resp.status_code}: {resp.text}"}), 502
    except requests.RequestException as exc:
        return jsonify({"error": str(exc)}), 502


@app.route("/api/template")
def api_template():
    """Return the example cluster YAML as plain text."""
    return CLUSTER_TEMPLATE, 200, {"Content-Type": "text/plain; charset=utf-8"}


@app.route("/api/create-cluster", methods=["POST"])
def api_create_cluster():
    """
    Validate submitted YAML, extract the cluster name, and commit the file
    to clusters/<name>.yaml via the GitHub Contents API — which automatically
    triggers the cluster-apply workflow.
    """
    if not GITHUB_TOKEN:
        return jsonify({"error": "GITHUB_TOKEN env var is not set"}), 500
    if not GITHUB_REPO:
        return jsonify({"error": "GITHUB_REPO env var is not set"}), 500

    body = request.get_json(silent=True) or {}
    manifest = body.get("manifest", "")
    if not manifest or not manifest.strip():
        return jsonify({"error": "manifest is required"}), 400

    # ── Parse and validate YAML ──────────────────────────────────────────────
    try:
        doc = yaml.safe_load(manifest)
    except yaml.YAMLError as exc:
        return jsonify({"error": f"Invalid YAML: {exc}"}), 400

    if not isinstance(doc, dict):
        return jsonify({"error": "Manifest must be a YAML mapping"}), 400

    cluster_name = (doc.get("metadata") or {}).get("name", "").strip()
    if not cluster_name:
        return jsonify({"error": "metadata.name is required"}), 400
    if not _CLUSTER_NAME_RE.match(cluster_name):
        return jsonify({"error": f"Invalid cluster name '{cluster_name}': must match [a-zA-Z0-9][a-zA-Z0-9_-]{{0,62}}"}), 400

    file_path = f"clusters/{cluster_name}.yaml"

    # ── Check if the file already exists (get its SHA for update, or error) ─
    contents_url = f"{API_BASE}/repos/{GITHUB_REPO}/contents/{file_path}"
    existing = _gh_get(contents_url)
    if existing.get("sha") and not body.get("overwrite"):
        return jsonify({
            "error": f"clusters/{cluster_name}.yaml already exists. Set overwrite=true to replace it.",
            "exists": True,
        }), 409

    # ── Commit the file via GitHub Contents API ──────────────────────────────
    content_b64 = base64.b64encode(manifest.encode()).decode()
    commit_payload: dict = {
        "message": f"feat: add cluster {cluster_name}",
        "content": content_b64,
        "branch":  GITHUB_REF,
    }
    if existing.get("sha"):
        commit_payload["sha"] = existing["sha"]  # required for updates

    try:
        resp = requests.put(
            contents_url,
            headers=_headers(),
            json=commit_payload,
            timeout=15,
        )
        if resp.status_code in (200, 201):
            return jsonify({"ok": True, "cluster": cluster_name, "path": file_path})
        return jsonify({"error": f"GitHub API returned {resp.status_code}: {resp.text}"}), 502
    except requests.RequestException as exc:
        return jsonify({"error": str(exc)}), 502


@app.route("/")
def index():
    return render_template("index.html", repo=GITHUB_REPO)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port, debug=False)
