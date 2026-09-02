#!/bin/bash
# cfn-init asset: CloudWatch agent install + the log/metric collection config for a CoreNova host.
set -xeuo pipefail

LOG_GROUP="${CFNOVA_LOG_GROUP:-/corenova/apps}"
REGION="${CFNOVA_AWS_REGION:-$(curl -s --max-time 2 http://169.254.169.254/latest/meta-data/placement/region || true)}"

if ! command -v amazon-cloudwatch-agent >/dev/null 2>&1; then
  curl -fsSL "https://s3.${REGION}.amazonaws.com/amazoncloudwatch-agent-${REGION}/ubuntu/amd64/latest/amazon-cloudwatch-agent.deb" \
    -o /tmp/amazon-cloudwatch-agent.deb
  dpkg -i /tmp/amazon-cloudwatch-agent.deb
fi

cat > /opt/aws/amazon-cloudwatch-agent/etc/corenova-config.json <<EOF
{
  "logs": {
    "logs_collected": {
      "files": {
        "collect_list": [
          { "file_path": "/var/log/corenova/*.log", "log_group_name": "${LOG_GROUP}", "log_stream_name": "{instance_id}/corenova", "timezone": "UTC" },
          { "file_path": "/var/log/nginx/error.log", "log_group_name": "${LOG_GROUP}", "log_stream_name": "{instance_id}/nginx-error", "timezone": "UTC" },
          { "file_path": "/var/log/nginx/corenova-*.access.log", "log_group_name": "${LOG_GROUP}", "log_stream_name": "{instance_id}/nginx-access", "timezone": "UTC" },
          { "file_path": "/var/log/syslog", "log_group_name": "${LOG_GROUP}", "log_stream_name": "{instance_id}/syslog", "timezone": "UTC" }
        ]
      }
    }
  },
  "metrics": {
    "namespace": "CoreNova",
    "metrics_collected": {
      "cpu": { "measurement": ["usage_active"], "totalcpu": false },
      "mem": { "measurement": ["used", "available"] },
      "disk": { "measurement": ["used_percent"], "disk_resources": ["nvme0n1p1", "xvda"] },
      "swap": { "measurement": ["used"] }
    }
  }
}
EOF

systemctl enable amazon-cloudwatch-agent
/opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl \
  -a fetch-config -m ec2 -s \
  -c file:/opt/aws/amazon-cloudwatch-agent/etc/corenova-config.json
systemctl is-active amazon-cloudwatch-agent
