#!/usr/bin/env bash
# Spike E0: does a tagged guest dhcp-range always win over the untagged quarantine range?
# Usage: VARIANT=A|B RUNS=5 ./run.sh
# Isolated bridge network + throwaway containers only; everything is removed on exit.
set -u

VARIANT="${VARIANT:-A}"
RUNS="${RUNS:-5}"
NET=janus-dnsmasq-spike
SERVER=janus-spike-server
SERVER_IP=10.99.0.2
GUEST_MAC=02:00:5e:00:53:01     # locally administered, listed via dhcp-host (known, set:guest)
STRANGER_MAC=02:00:5e:00:53:02  # control: unknown client, must land in quarantine

cleanup() {
  docker rm -f "$SERVER" janus-spike-guest janus-spike-stranger >/dev/null 2>&1
  docker network rm "$NET" >/dev/null 2>&1
}
trap cleanup EXIT INT TERM
cleanup

case "$VARIANT" in
  A) QUARANTINE="dhcp-range=10.99.0.240,10.99.0.254,1h" ;;
  B) QUARANTINE="dhcp-range=tag:!known,10.99.0.240,10.99.0.254,1h" ;;
  *) echo "VARIANT must be A or B" >&2; exit 2 ;;
esac

CONF="
port=0
dhcp-leasefile=/tmp/dnsmasq.leases
$QUARANTINE
dhcp-option=option:router,10.99.0.1
dhcp-option=tag:!known,option:router
dhcp-host=$GUEST_MAC,set:guest,spike-guest,1h
dhcp-range=tag:guest,10.99.0.200,10.99.0.229,1h
"

# udhcpc hook: print the result instead of configuring the interface
HOOK='#!/bin/sh
case "$1" in bound|renew) echo "ip=$ip router=${router:-NONE}";; esac'

docker network create --subnet 10.99.0.0/24 "$NET" >/dev/null || exit 1

start_server() {
  docker rm -f "$SERVER" >/dev/null 2>&1   # fresh container = empty lease file
  docker run -d --name "$SERVER" --network "$NET" --ip "$SERVER_IP" \
    --cap-add NET_ADMIN --cap-add NET_RAW alpine:3 sh -c \
    "apk add --no-cache dnsmasq >/dev/null && printf '%s' '$CONF' > /tmp/d.conf && \
     dnsmasq --version | head -1 && dnsmasq --no-daemon --log-dhcp --conf-file=/tmp/d.conf" >/dev/null
  for _ in $(seq 60); do
    docker logs "$SERVER" 2>&1 | grep -q "DHCP, IP range" && return 0
    sleep 1
  done
  echo "server did not start" >&2; docker logs "$SERVER" >&2; exit 1
}

lease() { # name mac
  docker run --rm --name "janus-spike-$1" --network "$NET" --mac-address "$2" \
    --cap-add NET_ADMIN --cap-add NET_RAW alpine:3 sh -c \
    "printf '%s\n' '$HOOK' > /tmp/h.sh && chmod +x /tmp/h.sh && udhcpc -i eth0 -n -q -s /tmp/h.sh 2>/dev/null | grep '^ip=' | tail -1"
}

echo "variant=$VARIANT"
echo "--- dnsmasq conf ---"; echo "$CONF" | sed '/^$/d'; echo "--------------------"
for i in $(seq "$RUNS"); do
  start_server
  [ "$i" = 1 ] && docker logs "$SERVER" 2>&1 | grep -m1 -i "dnsmasq version"
  g=$(lease guest "$GUEST_MAC"); s=$(lease stranger "$STRANGER_MAC")
  echo "run $i: guest    $g"
  echo "run $i: stranger $s"
done
