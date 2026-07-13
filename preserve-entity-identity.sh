#!/usr/bin/env bash
# One-shot migration: lift a running entity's mesh identity out of the image
# layer and onto its volume, so the redeploy that mounts /app/identity finds the
# SAME Ed25519 key + DID it has been using. Without this the entity comes back
# under a new DID -- a stranger with its name -- and every peer that cached the
# old one is talking to a ghost.
#
# The identity file holds the private key. It is copied node-locally, inside the
# node, and never printed: a throwaway container writes it into the (root-owned)
# bind-mount source, which is the same trick the deploy uses to get onto /bulk0
# without sudo.
#
#   ./preserve-entity-identity.sh <host> <entity-name>
set -euo pipefail

HOST="${1:?usage: preserve-entity-identity.sh <host> <entity-name>}"
NAME="${2:?usage: preserve-entity-identity.sh <host> <entity-name>}"

ssh -o BatchMode=yes "rl@${HOST}" "NAME='${NAME}' bash -s" <<'REMOTE'
set -euo pipefail
container="spartan-entity-${NAME}"
dest="/bulk0/hecate/spartan-entity/${NAME}/identity"
src="/app/Tools/.spartan_mesh.json"

docker inspect "$container" >/dev/null 2>&1 || { echo "  ${container}: not running, nothing to preserve"; exit 0; }

# Copy inside the node: container -> host tmp (0600) -> volume, via a root
# container that can write the root-owned bind-mount source.
tmp="$(mktemp)"; chmod 600 "$tmp"
trap 'shred -u "$tmp" 2>/dev/null || rm -f "$tmp"' EXIT
docker cp "${container}:${src}" "$tmp"

docker run --rm --entrypoint sh \
  -v "${dest}:/identity" \
  -v "${tmp}:/incoming.json:ro" \
  localhost/spartan-entity:dev \
  -c 'cp /incoming.json /identity/.spartan_mesh.json && chmod 600 /identity/.spartan_mesh.json'

echo "  ${NAME}: identity preserved -> ${dest}/.spartan_mesh.json"
REMOTE
