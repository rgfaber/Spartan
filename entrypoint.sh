#!/bin/sh
# Headless Spartan entity over the Macula mesh.
#
#   inbound : macula_radio bridge streams the entity's mesh inbox into
#             alerts/*.alert -> Spartan's FileWatcher (its only input in
#             headless mode).
#   cognition: spartan.py --headless, backend = Groq (spartan_config.yaml).
#   outbound: the entity invokes Tools/SpartanRadio.py (mesh drop-in) whenever
#             it decides to message a peer.
#
# One Ed25519+UCAN identity is minted once and shared by both directions
# (Tools/.spartan_mesh.json), so inbound and outbound speak as the same entity.
set -e
cd /app
mkdir -p alerts Soul

: "${GEMINI_API_KEY:?GEMINI_API_KEY must be set (active backend = gemini_flash)}"
: "${SPARTAN_MESH_URL:?SPARTAN_MESH_URL must be set (home node ingress)}"
: "${SPARTAN_MESH_NAME:?SPARTAN_MESH_NAME must be set (entity mesh name)}"

# The mesh identity lives on a VOLUME, not in the image layer: it is the
# entity's DID. A container-local identity means a new DID on every restart --
# a new stranger on the mesh each time, while peers still resolve the dead one.
export SPARTAN_MESH_STATE="${SPARTAN_MESH_STATE:-/app/identity/.spartan_mesh.json}"
mkdir -p "$(dirname "$SPARTAN_MESH_STATE")"

# Mint / load the shared mesh identity, and re-assert it with the home node
# (idempotent), before either direction starts.
python3 -c "import sys; sys.path.insert(0,'Tools'); import SpartanRadio; SpartanRadio.ensure_registered(); print('[entity] mesh identity ready')"

# Inbound bridge (background): mesh inbox -> alerts/*.alert for the FileWatcher.
# --config goes AFTER `bridge`: the bridge subparser also declares --config, so
# a top-level --config is shadowed by its None default.
#
# Respawned forever: the bridge retries HTTP faults itself, but the SSE stream
# also dies in ways it cannot catch (the node cycling, or a Celeron busy with
# cognition dropping the connection mid-frame). A dead bridge is a deaf entity
# -- it is the ONLY inbound path in headless mode -- and nothing else would
# notice, so it is supervised here rather than trusted to stay up.
while true; do
    python3 Tools/macula_radio.py bridge --config "$SPARTAN_MESH_STATE" --alerts-dir alerts
    echo "[entity] bridge exited; respawning in 2s"
    sleep 2
done &

# The entity: headless autonomous cognition on Groq. PID 1 -> container lifecycle.
exec python3 spartan.py --headless
