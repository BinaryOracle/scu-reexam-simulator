#!/bin/sh
# Native TURN loads its certificate at startup. Renew the private copy as a pair.
set -eu
[ "${RENEWED_LINEAGE:-}" = /etc/letsencrypt-scu/live/scu-ip ] || exit 0
install -o root -g scu-livekit -m 640 "$RENEWED_LINEAGE/fullchain.pem" /etc/scu-live/tls/fullchain.pem.new
install -o root -g scu-livekit -m 640 "$RENEWED_LINEAGE/privkey.pem" /etc/scu-live/tls/privkey.pem.new
mv /etc/scu-live/tls/fullchain.pem.new /etc/scu-live/tls/fullchain.pem
mv /etc/scu-live/tls/privkey.pem.new /etc/scu-live/tls/privkey.pem
systemctl try-restart scu-livekit
