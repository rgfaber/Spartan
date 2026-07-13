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

# Mint / load the shared mesh identity before either direction starts.
python3 -c "import sys; sys.path.insert(0,'Tools'); import SpartanRadio; SpartanRadio._load_or_register(); print('[entity] mesh identity ready')"

# Inbound bridge (background): mesh inbox -> alerts/*.alert for the FileWatcher.
python3 Tools/macula_radio.py --config Tools/.spartan_mesh.json bridge --alerts-dir alerts &

# The entity: headless autonomous cognition on Groq. PID 1 -> container lifecycle.
exec python3 spartan.py --headless
