#!/bin/bash
# cfn-init asset: renders the systemd unit that runs the application container.
# Nothing about the app image or port is baked in - both arrive as CFN parameters, so the same
# template verifies Ghost today and any other registered app tomorrow.
set -xeuo pipefail

APP_NAME="${CFNOVA_APP_NAME:?}"
IMAGE_REFERENCE="${CFNOVA_IMAGE_REFERENCE:?}"
CONTAINER_PORT="${CFNOVA_CONTAINER_PORT:?}"
DATA_DIR="${CFNOVA_DATA_DIR:-/var/lib/corenova/app/data}"
DATA_MOUNT="${CFNOVA_DATA_CONTAINER_PATH:-/data}"
APP_URL="${CFNOVA_APP_URL:-}"
EXTRA_ENV_FILE="${CFNOVA_EXTRA_ENV_FILE:-}"
LOG_GROUP="${CFNOVA_LOG_GROUP:-/corenova/apps}"
AWS_REGION="${CFNOVA_AWS_REGION:-us-east-1}"
HEALTH_PATH="${CFNOVA_HEALTH_PATH:-/}"
ENV_FILE="/opt/corenova/env/${APP_NAME}.env"

install -d -m 0755 "$DATA_DIR"
mkdir -p /opt/corenova/env

cat > "$ENV_FILE" <<EOF
CORENOVA_APP_IMAGE=${IMAGE_REFERENCE}
CORENOVA_CONTAINER_PORT=${CONTAINER_PORT}
CORENOVA_DATA_DIR=${DATA_DIR}
CORENOVA_APP_URL=${APP_URL}
EOF
if [ -n "$EXTRA_ENV_FILE" ] && [ -s "$EXTRA_ENV_FILE" ]; then
  cat "$EXTRA_ENV_FILE" >> "$ENV_FILE"
fi
chown root:corenova "$ENV_FILE"
chmod 0640 "$ENV_FILE"

cat > "/etc/systemd/system/corenova-${APP_NAME}.service" <<EOF
[Unit]
Description=CoreNova application container (${APP_NAME})
After=docker.service network-online.target
Requires=docker.service

[Service]
Type=simple
Restart=always
RestartSec=5
EnvironmentFile=${ENV_FILE}
ExecStartPre=-/usr/bin/docker rm -f ${APP_NAME}
ExecStartPre=/usr/bin/docker pull ${IMAGE_REFERENCE}
ExecStart=/usr/bin/docker run --rm --name ${APP_NAME} \\
  --label corenova.app=${APP_NAME} \\
  --log-driver awslogs --log-opt awslogs-group=${LOG_GROUP} --log-opt awslogs-stream=${APP_NAME} --log-opt awslogs-region=${AWS_REGION} \\
  --health-cmd "curl -sf http://127.0.0.1:${CONTAINER_PORT}${HEALTH_PATH} || exit 1" \\
  --health-interval 30s --health-timeout 5s --health-retries 3 --health-start-period 60s \\
  --stop-timeout 30 \\
  -p 127.0.0.1:${CONTAINER_PORT}:${CONTAINER_PORT} \\
  -v ${DATA_DIR}:${DATA_MOUNT} \\
  --env-file ${ENV_FILE} \\
  ${IMAGE_REFERENCE}
ExecStop=/usr/bin/docker stop ${APP_NAME}

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "corenova-${APP_NAME}"
systemctl restart "corenova-${APP_NAME}"
sleep 5
systemctl is-active "corenova-${APP_NAME}"
docker ps --filter "name=^/${APP_NAME}$" --format '{{.Names}} {{.Status}}'
