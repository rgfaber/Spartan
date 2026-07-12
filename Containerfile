# Headless Spartan entity for the Macula mesh (fork of CorticalComputer/Spartan).
#
# Lean by design: LanceDB is embedded (light, Rust) and stays in-process, but
# the embedding MODEL runs in a separate Ollama sidecar (active_embedding =
# qwen3_0_6b_ollama, ollama_host localhost:11434 via host networking) -- so this
# image carries no torch / sentence-transformers. Cognition is Groq
# (OpenAI-compatible). Comms ride the mesh via Tools/SpartanRadio.py (outbound
# drop-in) + Tools/macula_radio.py bridge (inbound -> alerts/*.alert).
FROM docker.io/python:3.12-slim
WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Groq (openai lib) + LanceDB (embedded vector store) + the bridge's requests /
# cryptography + pyyaml config. No torch: embeddings are served by Ollama.
RUN pip install --no-cache-dir \
    pyyaml openai requests cryptography lancedb

COPY . /app
RUN chmod +x /app/entrypoint.sh

ENV PYTHONUNBUFFERED=1
# Overridden per node: GROQ_API_KEY, SPARTAN_MESH_URL, SPARTAN_MESH_NAME.
ENTRYPOINT ["/app/entrypoint.sh"]
