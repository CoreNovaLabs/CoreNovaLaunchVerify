#!/bin/bash
# cfn-init asset: installs the Docker engine on a public (unmodified) Ubuntu AMI.
# Filename must keep the substring "docker" - platformref.compute_revisions() keys
# docker_runtime_revision off it, and the Platform Contract invalidation rule §5 depends on it.
set -xeuo pipefail

export DEBIAN_FRONTEND=noninteractive
. /etc/os-release

install -d -m 0755 /etc/apt/keyrings /opt/corenova/bin /var/log/corenova

if command -v dockerd >/dev/null 2>&1; then
  echo "[corenova] docker already present: $(docker --version)"
else
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -y
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi

cat > /etc/docker/daemon.json <<'JSON'
{
  "log-driver": "json-file",
  "log-opts": { "max-size": "10m", "max-file": "3" },
  "live-restore": true,
  "default-address-pools": [{ "base": "172.28.0.0/16", "size": 24 }]
}
JSON

systemctl daemon-reload
systemctl enable docker
systemctl restart docker

for who in ubuntu corenova; do
  id -u "$who" >/dev/null 2>&1 && usermod -aG docker "$who" || true
done

# Proof of life for the runtime, before any application image is involved.
docker version
docker info --format '{{.ServerVersion}} {{.OperatingSystem}}'
docker run --rm "${CFNOVA_SMOKE_IMAGE:-alpine:3.20}" /bin/sh -c 'echo docker-run-ok'
