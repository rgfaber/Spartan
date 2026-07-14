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
#
# LanceDB (LTM's vector store) is gated behind WITH_LANCEDB, default off: the
# beam-cluster Celerons (Goldmont, no AVX) SIGILL on LanceDB's AVX2 Rust core,
# and the SIGILL is uncatchable, so ltm.py's `try: import lancedb` must degrade
# to lancedb=None (LTM off in spartan_config.yaml). Build with
# `--build-arg WITH_LANCEDB=1` on an AVX2 host (e.g. msi00) for a long-lived
# entity that needs deep vector recall, e.g. the scribe.
ARG WITH_LANCEDB=0
RUN pip install --no-cache-dir \
    pyyaml openai google-generativeai requests cryptography \
    && if [ "$WITH_LANCEDB" = "1" ]; then pip install --no-cache-dir lancedb; fi

COPY . /app
RUN chmod +x /app/entrypoint.sh

ENV PYTHONUNBUFFERED=1
# Overridden per node: GROQ_API_KEY, SPARTAN_MESH_URL, SPARTAN_MESH_NAME.
ENTRYPOINT ["/app/entrypoint.sh"]
