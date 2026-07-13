#!/usr/bin/env bash
# Deploy one headless Spartan entity onto a node, homed on the local
# hecate-spartan mesh node. Requires the spartan-entity image already loaded on
# the host.
#
# EVERY MIND GETS ITS OWN KEY. Google's free tier meters per Cloud PROJECT, so
# two minds sharing a key throttle each other, and a 429 mid-cycle is
# indistinguishable from "the entity is broken". The key is looked up by entity
# name in ~/.gemini-api-keys/.spartan-<name> (one project per mind), and lands
# in a per-entity 0600 env-file on the node: ~/.spartan-entity-<name>.env.
#
# The key never touches argv, ps, logs, or shell history: it is streamed over
# ssh stdin into the env-file.
#
#   ./deploy-mesh-entity.sh <host> <mesh-name> [node-url]
#   SPARTAN_BACKEND=gemini_flash_latest ./deploy-mesh-entity.sh ...   (default)
set -euo pipefail

HOST="${1:?usage: deploy-mesh-entity.sh <host> <mesh-name> [node-url]}"
NAME="${2:?usage: deploy-mesh-entity.sh <host> <mesh-name> [node-url]}"
NODE_URL="${3:-http://127.0.0.1:8471}"
KEYDIR="${GEMINI_KEY_DIR:-$HOME/.gemini-api-keys}"
KEYFILE="${KEYDIR}/.spartan-${NAME}"

# models/gemini-2.5-flash is closed to new projects, so a fresh key 404s on it,
# and so do the aliases that resolve to it. gemini_flash_3 names an explicit
# model (gemini-3-flash-preview) that a new key can actually call.
BACKEND="${SPARTAN_BACKEND:-gemini_flash_3}"

# 1. Place this mind's key in its own 0600 env-file on the node (stdin, not argv).
#
#    The KEYFILE wins over an ambient $GEMINI_API_KEY on purpose. A shared key
#    exported by a shell profile is precisely the accident this change exists to
#    prevent: it deploys silently, every mind gets the same quota, and the first
#    symptom is four entities 429ing at once and looking broken.
if [ -r "$KEYFILE" ]; then
  KEY="$(tr -d '\r\n' <"$KEYFILE")"
  echo "  key: ${KEYFILE##*/} (own project, own quota)"
elif [ -n "${GEMINI_API_KEY:-}" ]; then
  KEY="$GEMINI_API_KEY"
  echo "  key: \$GEMINI_API_KEY from the environment (no ${KEYFILE##*/}); this mind"
  echo "       shares whatever quota that key belongs to"
else
  echo "no key for '${NAME}': expected ${KEYFILE}, and GEMINI_API_KEY is unset" >&2
  echo "test keys first with hecate-spartan/scripts/test-gemini-keys.sh" >&2
  exit 1
fi

printf 'GEMINI_API_KEY=%s\n' "$KEY" \
  | ssh -o BatchMode=yes "rl@${HOST}" \
      "install -m600 /dev/stdin \"\$HOME/.spartan-entity-${NAME}.env\""
unset KEY

# 2. Run the entity (host net -> reaches local node :8471 + ollama :11434).
#    Soul/ + ltm_db/ + alerts/ persist on /bulk0 so the mind survives restarts,
#    and identity/ carries the Ed25519 key + UCAN so it survives as the SAME
#    mind: a fresh DID per restart leaves stale registrations behind and peers
#    resolving a name to an entity that no longer listens.
#    No watchtower label: this fleet is rolled deliberately, not cycled under
#    the entities' feet.
ssh -o BatchMode=yes "rl@${HOST}" \
    "NAME='${NAME}' NODE_URL='${NODE_URL}' BACKEND='${BACKEND}' bash -s" <<'REMOTE'
set -e
data="/bulk0/hecate/spartan-entity/${NAME}"
docker rm -f "spartan-entity-${NAME}" >/dev/null 2>&1 || true
docker run -d --name "spartan-entity-${NAME}" --restart unless-stopped --network host \
  --env-file "$HOME/.spartan-entity-${NAME}.env" \
  -e SPARTAN_MESH_URL="${NODE_URL}" \
  -e SPARTAN_MESH_NAME="${NAME}" \
  -e SPARTAN_BACKEND="${BACKEND}" \
  -e SPARTAN_MESH_STATE=/app/identity/.spartan_mesh.json \
  -v "${data}/Soul:/app/Soul" \
  -v "${data}/ltm_db:/app/ltm_db" \
  -v "${data}/alerts:/app/alerts" \
  -v "${data}/identity:/app/identity" \
  localhost/spartan-entity:dev >/dev/null
echo "  spartan-entity-${NAME} launched (home ${NODE_URL})"
REMOTE
