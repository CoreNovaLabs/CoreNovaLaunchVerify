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
APP_URL_ENV_NAME="${CFNOVA_APP_URL_ENV_NAME:-}"
EXTRA_ENV_FILE="${CFNOVA_EXTRA_ENV_FILE:-}"
LOG_GROUP="${CFNOVA_LOG_GROUP:-/corenova/apps}"
AWS_REGION="${CFNOVA_AWS_REGION:-us-east-1}"
ENV_FILE="/opt/corenova/env/${APP_NAME}.env"

# LaunchUrl is optional because the instance public DNS name only exists after launch.
# Resolve it through IMDSv2 so apps such as Ghost receive a correct absolute base URL.
if [ -z "$APP_URL" ]; then
  set +x
  IMDS_TOKEN="$(curl -fsS -X PUT -H 'X-aws-ec2-metadata-token-ttl-seconds: 60' http://169.254.169.254/latest/api/token || true)"
  if [ -n "$IMDS_TOKEN" ]; then
    PUBLIC_DNS="$(curl -fsS -H "X-aws-ec2-metadata-token: ${IMDS_TOKEN}" http://169.254.169.254/latest/meta-data/public-hostname || true)"
    if [ -n "$PUBLIC_DNS" ]; then
      APP_URL="http://${PUBLIC_DNS}"
    fi
  fi
  set -x
fi

install -d -m 0755 "$DATA_DIR"
mkdir -p /opt/corenova/env

cat > "$ENV_FILE" <<EOF
CORENOVA_APP_IMAGE=${IMAGE_REFERENCE}
CORENOVA_CONTAINER_PORT=${CONTAINER_PORT}
CORENOVA_DATA_DIR=${DATA_DIR}
CORENOVA_APP_URL=${APP_URL}
EOF
if [ -n "$APP_URL_ENV_NAME" ] && [ -n "$APP_URL" ]; then
  printf '%s=%s\n' "$APP_URL_ENV_NAME" "$APP_URL" >> "$ENV_FILE"
fi
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
