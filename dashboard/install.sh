#!/usr/bin/env bash
# install.sh — Install pxmx-dashboard as a systemd service.
#
# Run as root on the target host:
#   sudo bash install.sh [SOURCE_DIR]
#
# SOURCE_DIR defaults to the directory containing this script.
# The script is idempotent: re-running it upgrades an existing installation.

set -euo pipefail

DEPLOY_DIR="/opt/pxmx-dashboard"
SERVICE_NAME="pxmx-dashboard"
RUN_USER="pxmx"
RUN_GROUP="pxmx"
ENV_DIR="/etc/pxmx-dashboard"
UNIT_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Helpers ────────────────────────────────────────────────────────────────────
info()  { echo "[install] $*"; }
die()   { echo "[install] ERROR: $*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "This script must be run as root (sudo bash install.sh)"

# ── 1. Service account ─────────────────────────────────────────────────────────
if ! id -u "${RUN_USER}" &>/dev/null; then
    info "Creating system user '${RUN_USER}'..."
    useradd --system --no-create-home --shell /usr/sbin/nologin \
        --comment "pxmx dashboard service" "${RUN_USER}"
else
    info "User '${RUN_USER}' already exists — skipping creation."
fi

# ── 2. Deploy directory ────────────────────────────────────────────────────────
info "Copying application files to ${DEPLOY_DIR}..."
install -d -m 755 "${DEPLOY_DIR}"
rsync -a --delete \
    --exclude '__pycache__' \
    --exclude '*.pyc' \
    --exclude '.env*' \
    --exclude 'venv/' \
    --exclude 'install.sh' \
    "${SOURCE_DIR}/" "${DEPLOY_DIR}/"
chown -R "${RUN_USER}:${RUN_GROUP}" "${DEPLOY_DIR}"

# ── 3. Python virtualenv ───────────────────────────────────────────────────────
VENV="${DEPLOY_DIR}/venv"
if [[ ! -d "${VENV}" ]]; then
    info "Creating virtualenv at ${VENV}..."
    python3 -m venv "${VENV}"
fi

info "Installing/upgrading Python dependencies..."
"${VENV}/bin/pip" install --quiet --upgrade pip
"${VENV}/bin/pip" install --quiet --upgrade -r "${DEPLOY_DIR}/requirements.txt"
chown -R "${RUN_USER}:${RUN_GROUP}" "${VENV}"

# ── 4. Environment file ────────────────────────────────────────────────────────
install -d -m 750 "${ENV_DIR}"
chown root:"${RUN_GROUP}" "${ENV_DIR}"

if [[ ! -f "${ENV_DIR}/env" ]]; then
    info "Creating env file template at ${ENV_DIR}/env..."
    install -m 640 -o root -g "${RUN_GROUP}" "${SOURCE_DIR}/env.example" "${ENV_DIR}/env"
    echo
    echo "  *** ACTION REQUIRED ***"
    echo "  Edit ${ENV_DIR}/env and set GITHUB_TOKEN and GITHUB_REPO before"
    echo "  starting the service."
    echo
else
    info "Env file ${ENV_DIR}/env already exists — not overwritten."
fi

# ── 5. Systemd unit ───────────────────────────────────────────────────────────
info "Installing systemd unit ${UNIT_FILE}..."
install -m 644 "${SOURCE_DIR}/${SERVICE_NAME}.service" "${UNIT_FILE}"

systemctl daemon-reload
systemctl enable "${SERVICE_NAME}.service"
info "Service '${SERVICE_NAME}' enabled."

# Only (re)start if env file has been configured
if grep -q "REPLACE_ME" "${ENV_DIR}/env" 2>/dev/null; then
    info "Skipping start: GITHUB_TOKEN not yet set in ${ENV_DIR}/env"
else
    info "Starting ${SERVICE_NAME}..."
    systemctl restart "${SERVICE_NAME}.service"
    systemctl status "${SERVICE_NAME}.service" --no-pager
fi

info "Done.  Useful commands:"
echo "  sudo systemctl status  ${SERVICE_NAME}"
echo "  sudo systemctl restart ${SERVICE_NAME}"
echo "  sudo journalctl -u ${SERVICE_NAME} -f"
