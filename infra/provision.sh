#!/bin/bash
# Runs inside the Packer builder (as root). Also the manual fallback if Packer fails:
#   launch an AL2023 instance, SSM in, `sudo IMAGE=ghcr.io/<owner>/streamlite:<sha7> bash provision.sh`,
#   then `aws ec2 create-image --instance-id <id> --name hsl-streamlite-manual-<sha7>`.
set -euo pipefail
: "${IMAGE:?IMAGE must be set, e.g. ghcr.io/<owner>/streamlite:<sha7>}"

dnf install -y docker
systemctl enable --now docker

for attempt in 1 2 3 4 5; do
  if docker pull "$IMAGE"; then break; fi
  if [ "$attempt" -eq 5 ]; then echo "docker pull failed (is the GHCR package public?)" >&2; exit 1; fi
  sleep $((attempt * 3))
done
echo "$IMAGE" >/etc/streamlite.image

# The env file is written by user_data at boot. The unit is installed but NOT enabled (fix F9),
# so it can never start with default settings before user_data has run.
cat >/etc/systemd/system/streamlite.service <<EOF
[Unit]
Description=StreamLite API (container)
After=docker.service network-online.target
Requires=docker.service
Wants=network-online.target

[Service]
EnvironmentFile=-/etc/streamlite.env
ExecStartPre=/usr/bin/test -f /etc/streamlite.env
ExecStartPre=-/usr/bin/docker rm -f streamlite
ExecStart=/usr/bin/docker run --rm --name streamlite --network host --env-file /etc/streamlite.env --log-opt max-size=50m --log-opt max-file=2 $IMAGE
ExecStop=/usr/bin/docker stop -t 10 streamlite
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl is-enabled streamlite && { echo "streamlite must stay disabled in the AMI" >&2; exit 1; }

# Smoke-test the image once on the builder, then remove the test container.
docker run -d --name provision-check --network host -e IMDS_ENABLED=false -e SSM_MODE=off "$IMAGE"
ok=0
for _ in $(seq 1 100); do
  if curl -sf -o /dev/null http://127.0.0.1:8000/healthz; then ok=1; break; fi
  sleep 0.1
done
docker rm -f provision-check >/dev/null
[ "$ok" -eq 1 ] || { echo "image did not become healthy on the builder" >&2; exit 1; }

# Keep the AMI small and free of per-instance state.
dnf clean all
rm -rf /var/cache/dnf /tmp/* /var/log/hsl-boot.log
cloud-init clean --logs || true
echo "provision ok: $IMAGE"
