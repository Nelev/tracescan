#!/bin/sh
# First-boot script of the demo's Lightsail instance (docs/deploy-plan.md, step 3), passed as
# --user-data to `aws lightsail create-instances`. POSIX sh, not bash: Lightsail prepends its own
# `#!/bin/sh` setup to the user data, so a bash shebang here is ignored. Also safe to run again
# by hand: `ssh ubuntu@<ip> 'sudo sh -s' < deploy/lightsail-init.sh`. Runs as root on Ubuntu 24.04: installs
# Docker Engine and the compose plugin from Docker's apt repository, lets `ubuntu` use Docker,
# and adds a 2 GB swap file as a safety net for `next build` and `uv sync`.
# Progress is in /var/log/cloud-init-output.log; /var/lib/tracescan-init-done marks success.
set -eu
export DEBIAN_FRONTEND=noninteractive

apt-get update
apt-get install -y ca-certificates curl git
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
. /etc/os-release
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
  > /etc/apt/sources.list.d/docker.list
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker
usermod -aG docker ubuntu

if [ ! -f /swapfile ]; then
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

touch /var/lib/tracescan-init-done
