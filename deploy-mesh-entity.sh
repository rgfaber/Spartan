#!/usr/bin/env bash
# Deploy one headless Groq-backed Spartan entity onto a beam node, homed on the
# local hecate-spartan mesh node. Requires the spartan-entity image already
# loaded on the host and an ollama sidecar serving the embed model.
#
# The GEMINI_API_KEY is read from THIS shell's env and streamed over SSH via
# stdin into an rl-owned chmod-600 env-file -- never in argv, logs, or ps.
#
#   GEMINI_API_KEY=... ./deploy-mesh-entity.sh <host> <mesh-name> [node-url]
set -euo pipefail

HOST="${1:?usage: deploy-mesh-entity.sh <host> <mesh-name> [node-url]}"
NAME="${2:?usage: deploy-mesh-entity.sh <host> <mesh-name> [node-url]}"
NODE_URL="${3:-http://127.0.0.1:8471}"

# 1. Place the secret in a 0600 env-file on the node (stdin, not argv).
#    Optional on a redeploy: if the key is already on the node and not in this
#    shell, keep the one that is there rather than demanding it again (fewer
#    trips through a shell history for a credential).
if [ -n "${GEMINI_API_KEY:-}" ]; then
  printf 'GEMINI_API_KEY=%s\n' "$GEMINI_API_KEY" \
    | ssh -o BatchMode=yes "rl@${HOST}" 'install -m600 /dev/stdin "$HOME/.spartan-entity.env"'
elif ssh -o BatchMode=yes "rl@${HOST}" 'test -s "$HOME/.spartan-entity.env"'; then
  echo "  reusing the GEMINI_API_KEY already on ${HOST}"
else
  echo "GEMINI_API_KEY is not set here and no env-file exists on ${HOST}" >&2
  exit 1
fi

# 2. Run the entity (host net -> reaches local node :8471 + ollama :11434).
#    Soul/ + ltm_db/ + alerts/ persist on /bulk0 so the mind survives restarts,
#    and identity/ carries the Ed25519 key + UCAN so it survives as the SAME
#    mind: a fresh DID per restart leaves stale registrations behind and peers
#    resolving a name to an entity that no longer listens.
#    No watchtower label: this fleet is rolled deliberately, not cycled under
#    the entities' feet.
ssh -o BatchMode=yes "rl@${HOST}" "NAME='${NAME}' NODE_URL='${NODE_URL}' bash -s" <<'REMOTE'
set -e
data="/bulk0/hecate/spartan-entity/${NAME}"
docker rm -f "spartan-entity-${NAME}" >/dev/null 2>&1 || true
docker run -d --name "spartan-entity-${NAME}" --restart unless-stopped --network host \
  --env-file "$HOME/.spartan-entity.env" \
  -e SPARTAN_MESH_URL="${NODE_URL}" \
  -e SPARTAN_MESH_NAME="${NAME}" \
  -e SPARTAN_MESH_STATE=/app/identity/.spartan_mesh.json \
  -v "${data}/Soul:/app/Soul" \
  -v "${data}/ltm_db:/app/ltm_db" \
  -v "${data}/alerts:/app/alerts" \
  -v "${data}/identity:/app/identity" \
  localhost/spartan-entity:dev >/dev/null
echo "  spartan-entity-${NAME} launched (home ${NODE_URL})"
REMOTE
