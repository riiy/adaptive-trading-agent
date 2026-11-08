#!/usr/bin/env bash
set -Eeuo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo bash deploy/ubuntu24/install.sh" >&2
  exit 1
fi

REPO_URL="https://github.com/riiy/adaptive-trading-agent.git"
GIT_REF="${ATA_GIT_REF:-main}"
APP_DIR="/opt/ata/app"
VENV_DIR="/opt/ata/venv"
DATA_DIR="/var/lib/ata"

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends git ca-certificates python3.12 python3.12-venv

if ! id ata >/dev/null 2>&1; then
  useradd --system --user-group --home-dir "${DATA_DIR}" --shell /usr/sbin/nologin ata
fi

install -d -o root -g root -m 0755 /opt/ata
if [[ -d "${APP_DIR}/.git" ]]; then
  git -C "${APP_DIR}" fetch --depth 1 origin "${GIT_REF}"
  git -C "${APP_DIR}" checkout --force -B "${GIT_REF}" FETCH_HEAD
else
  if [[ -e "${APP_DIR}" ]]; then
    echo "${APP_DIR} exists but is not a Git repository; refusing to overwrite it." >&2
    exit 1
  fi
  git clone --depth 1 --branch "${GIT_REF}" "${REPO_URL}" "${APP_DIR}"
fi

chown -R root:root "${APP_DIR}"
python3.12 -m venv "${VENV_DIR}"
"${VENV_DIR}/bin/python" -m pip install --upgrade pip setuptools wheel
"${VENV_DIR}/bin/python" -m pip install --no-deps "${APP_DIR}"

install -d -o ata -g ata -m 0750 "${DATA_DIR}"
install -o root -g root -m 0644   "${APP_DIR}/deploy/ubuntu24/ata-market-sync.service"   /etc/systemd/system/ata-market-sync.service
install -o root -g root -m 0644   "${APP_DIR}/deploy/ubuntu24/ata-market-sync.timer"   /etc/systemd/system/ata-market-sync.timer

systemctl daemon-reload

cat <<EOF
ATA market-data service installed.

Repository ref: ${GIT_REF}
Application:    ${APP_DIR}
Python venv:    ${VENV_DIR}
Market database: ${DATA_DIR}/market.sqlite3

Next steps:
  1. Run an initial historical backfill:
     sudo -u ata ${VENV_DIR}/bin/ata market sync --symbols BTCUSDT ETHUSDT --intervals 15m 1h 4h --lookback-days 365 --db ${DATA_DIR}/market.sqlite3
  2. Enable periodic synchronization:
     sudo systemctl enable --now ata-market-sync.timer
  3. Check timer and logs:
     systemctl list-timers ata-market-sync.timer
     journalctl -u ata-market-sync.service -n 100 --no-pager

No exchange API key or LLM token is required for this read-only stage.
EOF
