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

# Cognition = Gemini (google-generativeai; Groq's free-tier 12k TPM can't fit
# Spartan's ~55k-token cycle -- the Genesis Core alone is ~50k). openai kept for
# the Groq/OpenAI providers. Plus the bridge's requests / cryptography + pyyaml.
# NO lancedb: the beam-cluster Celerons (Goldmont, no AVX) SIGILL on LanceDB's
# AVX2 Rust core, and the SIGILL is uncatchable. Omitting the package lets
# ltm.py's `try: import lancedb` degrade to lancedb=None cleanly; LTM is off
# in spartan_config.yaml. Add lancedb back only on AVX2 hosts for long-lived
# entities that need deep vector recall.
RUN pip install --no-cache-dir \
    pyyaml openai google-generativeai requests cryptography

COPY . /app
RUN chmod +x /app/entrypoint.sh

ENV PYTHONUNBUFFERED=1
# Overridden per node: GROQ_API_KEY, SPARTAN_MESH_URL, SPARTAN_MESH_NAME.
ENTRYPOINT ["/app/entrypoint.sh"]
