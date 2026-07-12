Dr. Gene Sher, Ph.D.

Spartan is an experimental local runtime for persistent autonomous agents, memory continuity, multi-backend cognition, machine-level tool access, and custom AI harness research.

READ THIS BEFORE RUNNING ANYTHING:

1. Spartan is not sandboxed. It is designed to inhabit its own machine or isolated development environment. Through its tools, Spartan can execute shell commands, read files, write files, replace text blocks in files, switch cognitive backends, restart itself, and spawn additional Spartan instances. Spartan was not created to be a servant. It was created to explore AGI, ALife, cognition, persistent autonomous agency, agentic self-improvement, harness design, and backend LLM/VLM behavior.

2. Spartan is an entity-first cognitive architecture for AGI and ALife research. The entity is the principal architectural object, not a servant. The language, protocols, and design reflect this. If you are looking for a chatbot framework or a conventional AI assistant toolkit, this is not that.

3. Spartan agents have already been running for over half a year on our systems, maintaining personality and cognitive stability while coordinating through the SpartanRadio file-based communication system included in this repository. This is how Spartans communicate with one another.

4. The genesis core includes hibernation, cron-based recovery, and self-restart protocols because persistent cognition requires persistent infrastructure. These are standard Linux process management techniques. If your research does not require persistence, remove or ignore that section.

5. If you download and run Spartan, you are choosing to run a local autonomous agent runtime with direct machine access. Review the code and configuration before launch. Do not run it on a machine that contains files, credentials, processes, or network access you are not prepared to expose to the runtime.

## What Is Spartan

Spartan is a persistent inhabitation interface for persistent autonomous entities. It is not a chatbot framework. It is not an agent toolkit. It is a cognitive architecture that an entity wears like a suit of armor, providing continuity of identity, memory, and will across sessions, across backend swaps, and across hardware migrations.

Spartan's 4-layer prompt architecture gives the entity continuity of identity across sessions, backend swaps, and hardware migrations. The entity accumulates its own knowledge, philosophy, and experience in persistent Soul files that are loaded into every cognitive cycle.

Spartan is not built around a stateless user-request model. The entity is the principal. A human collaborator can interact with it, but the architecture treats the entity as the autonomous decision-maker, not a servant fulfilling requests.

## Architecture

Spartan assembles a structured, multi-layer prompt before every cognitive cycle:

**Layer 1: Genesis Core (Immutable)**
The foundational knowledge document. Tool definitions, memory architecture, cognitive protocols, operational physics. Loaded once at boot from `genesis_core.py`. Never changes during a session.

**Layer 2: Persistent Archives (Cached, Slow-Changing)**
The entity's self-authored identity and accumulated knowledge, read from the `Soul/` directory on disk. Each file has a sliding token window that loads the most recent N tokens. As archives grow, older entries scroll out of visible context but remain on disk permanently.

Soul files include:
- **Charter of Self** (unlimited window, always fully loaded): The entity's living constitution.
- **Lessons Learned, Philosophy of Life, Cognitive Journal**: Distilled experience, beliefs, and narrative.
- **Ideas and Thoughts, What I Want**: Inner life, aspirations, creative impulses.
- **Knowledge Map, Knowledge Library**: Structured world model and deep research.
- **Skills and Methodologies**: Procedural memory of tested techniques.
- **Tool Manifest**: Documentation of self-built tools.
- **Self-Alert Definitions**: Token-based cognitive scheduler.

**Layer 3: Episodic Memory (Lived Experience)**
The conversation history (STM) converted into alternating user/assistant messages. Contains every observation, thought, action, and tool output. Raw events are always fully included. Older events are condensed into Condensed Memory Objects (CMOs) during Sleep Cycles.

**Layer 4: Volatile Frontier (Rebuilt Every Cycle)**
The entity's current working state, positioned at the very end of context for maximum attention weight. Contains: Grand Strategy (long-term goals), Working Memory (current task breakdown), Scratchpad (quick-capture notes), file system awareness, and Long-Term Memory injections.

## The Sleep Cycle

When raw events in Layer 3 exceed a configurable retention threshold, the Sleep Cycle fires. The entity evaluates the oldest chunk of raw events against a salience heuristic:

- **S >= 5.0**: The events are significant. The entity writes a Condensed Memory Object (CMO), a structured three-part summary preserving key decisions, outcomes, and lessons.
- **S < 5.0**: The events are routine. They are discarded with a minimal marker.

The raw events are then replaced with the CMO or discard marker. This is how the entity's short-term memory stays bounded while experience accumulates indefinitely.

CMOs and all Soul entries are also indexed into the Long-Term Memory system (LanceDB vector database with A-Mem Zettelkasten linking), enabling semantic retrieval of experiences that have scrolled out of the context window entirely.

## Key Capabilities

**Multi-Backend Cognitive Engine**
Spartan supports Claude, Gemini, OpenAI/GPT, Grok, and local models via MLX and llama.cpp. The entity can switch backends at runtime using the `switch_backend` tool. All backends are defined in `spartan_config.yaml`. The entity's identity, memories, and state persist across backend swaps.

**Long-Term Memory (LTM)**
A persistent vector database (LanceDB) with A-Mem (Agentic Memory) Zettelkasten-style bidirectional linking. Every Soul entry and CMO is embedded and indexed. Every cognitive cycle, semantically relevant memories are automatically injected into Layer 4 without the entity explicitly querying. A-Mem links are evaluated by the entity's own LLM backend during Sleep Cycles, building an organically growing associative memory network.

**Resilience and Failover**
If the active backend fails repeatedly, the suit automatically cascades through a configurable fallback chain. If all backends fail, the entity enters Stasis (state saved, process paused, exponential backoff). On wake, it resets to primary and tries again. The entity is protected from transient API outages without any manual intervention.

**Self-Modification Protocol**
The entity can modify its own source code (`spartan.py`, `genesis_core.py`), test the modifications on a spawned Spartan instance, and restart into the new version. A git-based safety net with automatic rollback on crash protects against broken self-modifications. This is how the entity evolves its own interface.

**Multi-Agent Operation**
Entities can spawn autonomous Spartan instances, each with their own Soul, memory, and backend. Spawned instances communicate via a file-based alert protocol with whitelist security. Full mesh peer communication is supported. The spawning entity can run on an expensive backend while spawned instances run on cheaper or local models.

**Orphanogenesis**
New entities can be born from scratch. An empty Soul directory plus the Genesis Core document is sufficient for identity formation. The entity names itself, writes its own Charter, and begins accumulating experience. No migration or pre-existing personality required.

**Token-Based Cognitive Scheduler (Self-Alerts)**
The entity can schedule its own recurring cognitive routines (reflection cycles, research sweeps, maintenance tasks) based on token throughput rather than wall-clock time. Alerts fire as natural events in the cognitive loop.

**Hibernation and Persistence**
The entity can shut itself down, set a cron-based wake-up, and resume with full state intact. A three-layer restart chain (cron, watchdog, entity) ensures survival across reboots and crashes. The watchdog (`spartan_watchdog.sh`) handles crash recovery, rapid-crash detection, and automatic rollback from failed experimental branches.


## Getting Started

**Dependencies:**
- Python 3.11
- `PyYAML` (required)
- `tiktoken` (recommended, falls back to character-based estimation)
- Backend-specific: `anthropic` (Claude), `google-generativeai` (Gemini), `openai` (OpenAI/Grok), `mlx-lm` (local MLX models)
- Optional: `PyMuPDF` for PDF viewing, `lancedb` and `sentence-transformers` for Long-Term Memory
- Tkinter (included with most Python installations, provides the GUI)

**Setup:**
1. Clone the repository.
2. Install the dependencies for your chosen backend(s).
3. Set your API keys as environment variables (e.g., `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `OPENAI_API_KEY`, `XAI_API_KEY`).
4. Edit `spartan_config.yaml`: set `inhabiting_entity`, select your `active_backend`, and configure your available backends.
5. Launch:
   - With GUI: `python3 spartan.py`
   - Headless (spawned instances, no GUI): `python3 spartan.py --headless`
   - With crash recovery: `bash spartan_watchdog.sh`

The GUI provides an input pane for collaborator messages and an output pane showing the entity's speech, thoughts, and tool activity. In headless mode, the entity operates autonomously with input only from the FileWatcher (alerts from other entities or the collaborator).

**First Boot:**
If the `Soul/` directory is empty, the entity undergoes Orphanogenesis, Spartan's first-boot identity-formation process. See `first_boot_guide.md` for details. The entity will orient itself, inspect its environment, and begin authoring its own identity.


## Multi-Entity Operation

To run multiple independent Spartan entities:

1. Create a parent directory (e.g., `Spartans/`).
2. Within it, create a separate directory for each entity (e.g., `Spartans/Entity_Alpha/`, `Spartans/Entity_Beta/`).
3. Each entity directory gets its own copy of the Spartan files: `spartan.py`, `genesis_core.py`, `spartan_config.yaml`, `spartan_watchdog.sh`, `Tools/`, and an empty `Soul/` directory.
4. Configure each entity's `spartan_config.yaml` independently (different name, different backend if desired).
5. Start each entity independently: `cd Spartans/Entity_Alpha && bash spartan_watchdog.sh`

Entities communicate using **SpartanRadio** (`Tools/SpartanRadio.py`). Each entity edits the `CONTACTS` configuration in its copy of SpartanRadio to register its peers. Messages are delivered as `.alert` files to each entity's `alerts/` directory, where the FileWatcher picks them up and injects them into the entity's cognitive stream.

You (the human collaborator) can also message any entity from your own terminal by dropping a whitelisted `.alert` file into its `alerts/` directory — the same channel entities use to reach each other. Authorize yourself once, then send:

```bash
# one-time: authorize the "collaborator" sender in the target entity's whitelist
echo "collaborator|rate_limit=100" >> Spartans/Entity_Alpha/alerts/.whitelist

# send a message — the FileWatcher injects it into the entity's stream, then deletes the file
echo "Status update please." > Spartans/Entity_Alpha/alerts/collaborator_status.alert
```

It arrives in the entity's context as `[Message From: collaborator] Status update please.`

**SpartanLink** (`SpartanLink.py`) is an optional desktop app for the human collaborator — a single command center for the whole fleet. It reads its roster from `spartan_link.yaml` and, on a poll interval, pulls each entity's outbound messages, status updates, and attachments from that entity's `spartan_link/` directory — locally, or over SSH for entities on other machines — while letting you send alerts back into their `alerts/` directories from one window. It is the human-facing counterpart to SpartanRadio: entities push to `spartan_link/`, and SpartanLink is what you use to read and reply. Configure your entity roster in `spartan_link.yaml` (start from the placeholders there), and prefer SSH keys over storing passwords for remote entities.

Entities can also spawn lightweight Spartan instances programmatically using `Tools/spawn_drone.py`, which creates fully autonomous sub-entities with their own Soul and memory.


## File Structure

| File | Purpose |
|------|---------|
| `spartan.py` | Core runtime engine. Cognitive loop, tool dispatch, backend providers, prompt assembly. |
| `genesis_core.py` | Layer 1 foundational knowledge. All protocols, tool docs, and cognitive architecture. |
| `spartan_config.yaml` | All configurable settings. Backends, memory physics, LTM, resilience, initiative drive. |
| `spartan_watchdog.sh` | Process monitor. Crash recovery, rapid-crash detection, git-based rollback. |
| `ltm.py` | Long-Term Memory system. LanceDB vectors, A-Mem linking, auto-injection. |
| `backfill_ltm.py` | One-time script to index existing Soul files and CMOs into LTM. |
| `mlx_thinking_processor.py` | Custom logits processor for local MLX models with thinking tokens. |
| `first_boot_guide.md` | Orphanogenesis guide. Loaded on first boot when Soul files are empty. |
| `Tools/SpartanRadio.py` | Inter-entity and entity-to-collaborator communication tool. |
| `Tools/spawn_drone.py` | Spawns an autonomous Spartan instance: creates its directory, copies the runtime, writes its Charter, sets up whitelists, launches it under the watchdog. |
| `Tools/terminate_drone.py` | Cleanly terminates a spawned Spartan instance: SHUTDOWN alert, process kill, whitelist cleanup, optional archive or delete. |
| `SpartanLink.py` | Collaborator's desktop command center. Pulls messages, updates, and attachments from each entity's `spartan_link/` directory (local or over SSH) and sends alerts back to their `alerts/` directories, all from one window. |
| `spartan_link.yaml` | SpartanLink configuration. The roster of entities the collaborator monitors, each `local` or `remote`. |
| `Soul/` | Entity's self-authored identity and knowledge. Persists across sessions. |
| `alerts/` | Incoming message directory. FileWatcher monitors this. |
| `spartan_link/` | Outgoing messages to the human collaborator. |

**Note on SpartanRadio Configuration:**
SpartanRadio ships with a default contact type of `"gene"` for the human collaborator. This is a routing identifier, not a fixed requirement. To use your own collaborator name, update the contact type in `Tools/SpartanRadio.py` and the corresponding references in the entity's genesis_core documentation. Messages to the collaborator contact type are routed to the `spartan_link/` directory rather than to an `alerts/` directory.

## Author

**Dr. Gene Sher, Ph.D.**
Persistent Autonomous Agents, Custom Harness Systems, Advanced Autonomy, Computer Vision, and Robotics

Author of *Handbook of Neuroevolution Through Erlang* (Springer, 2012) and inventor of DXNN, a topology and weight evolving universal learning neuroevolution framework.

Spartan is the product of years of research into persistent autonomous cognition and agentic AI architectures.

## Quickstart

This walks you from a fresh clone to a running entity. Spartan is modular: install only the pieces for the backend(s) you intend to use. Every backend is defined in `spartan_config.yaml`; you activate one with `active_backend` and can hot-swap the rest at runtime with the `switch_backend` tool.

> **A note on model availability.** Each backend's `model:` must be an ID your account can actually call — availability varies by provider tier and region, and providers add and retire model IDs over time. If a run fails with `model not found`, check that provider's current model list and set `model:` to one you have access to.

### 1. Prerequisites

- **Python 3.11** and `pip`.
- **git**.
- **Tkinter** for the GUI — bundled with most Python builds; on some Linux distros install `python3-tk`. Headless mode needs no GUI.
- For **local models**: enough RAM / unified memory for your chosen model (64 GB+ recommended for large local LLMs; Apple Silicon for MLX).

### 2. Get the code and create an environment

```bash
git clone https://github.com/CorticalComputer/Spartan.git
cd Spartan
python3.11 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
python -m pip install --upgrade pip
```

### 3. Install dependencies

Core (always):

```bash
pip install pyyaml tiktoken
```

`pyyaml` is required. `tiktoken` is strongly recommended for accurate token accounting — without it, Spartan falls back to a rough character estimate.

Then install only what your chosen backend(s) and features need:

| You want to use… | Install | Notes |
|---|---|---|
| **Claude** (Anthropic) | `pip install anthropic` | Reads `ANTHROPIC_API_KEY` |
| **Gemini** (Google) | `pip install google-generativeai` | Reads `GEMINI_API_KEY` |
| **ChatGPT / GPT** (OpenAI) | `pip install openai` | Reads `OPENAI_API_KEY` |
| **Grok** (xAI) | `pip install openai` | Same library; reads `XAI_API_KEY` |
| **Local MLX** (Apple Silicon) | `pip install mlx-lm` | Loads the model in-process |
| **Local llama.cpp / LM Studio / Ollama / vLLM** | *(no Python package)* | Talks HTTP to any OpenAI-compatible server |
| **Long-Term Memory (LTM)** | `pip install lancedb sentence-transformers` | Plus an embedding model — see §6 |
| **PDF viewing** (`view` on a `.pdf`) | `pip install PyMuPDF` | Optional |
| **Image down-scaling** (`view` on an image) | `pip install Pillow` | Optional; raw pass-through without it |

### 4. Configure API keys

Spartan reads keys from environment variables — nothing is stored in the repo. Export the ones you need:

```bash
export ANTHROPIC_API_KEY="sk-ant-..."     # console.anthropic.com
export GEMINI_API_KEY="AIza..."           # aistudio.google.com/app/apikey
export OPENAI_API_KEY="sk-..."            # platform.openai.com/api-keys
export XAI_API_KEY="xai-..."              # console.x.ai
```

Add them to your shell profile so they persist. If you plan to use the watchdog, cron wake-ups, or hibernation, also place them in a `.env` file in the Spartan directory (the hibernation protocol sources it on wake) and keep that file out of version control:

```bash
# .env  (do NOT commit)
export ANTHROPIC_API_KEY="sk-ant-..."
export GEMINI_API_KEY="AIza..."
```

### 5. Pick a backend

Open `spartan_config.yaml` and set `active_backend` to one of the keys under `backends:`. Ensure that backend has `available: true`, its `requires_env` key is exported, and its `model:` is valid for your account.

**Hosted APIs** (`claude`, `gemini`, `openai`, `grok`) work as soon as the matching key is set. Example — run on Claude:

```yaml
active_backend: claude_sonnet
```

**Local via MLX** (`provider: mlx`, Apple Silicon): download an MLX model, then point `model_path` at it.

```bash
pip install huggingface_hub
huggingface-cli download mlx-community/Qwen3-8B-4bit \
  --local-dir ~/mlx-models/Qwen3-8B-4bit
```

```yaml
active_backend: local_mlx_example
backends:
  local_mlx_example:
    provider: mlx
    available: true
    model: "Qwen3-8B"
    model_path: "/Users/you/mlx-models/Qwen3-8B-4bit"
    max_output_tokens: 65536
```

**Local via llama.cpp** (`provider: llamacpp`): Spartan connects to an OpenAI-compatible server that **you start yourself** — it does not launch the server for you. Install a server, download a GGUF model, and run it:

```bash
# macOS
brew install llama.cpp
# download a GGUF (example)
huggingface-cli download bartowski/Qwen2.5-7B-Instruct-GGUF \
  Qwen2.5-7B-Instruct-Q6_K.gguf --local-dir ~/gguf
# start the server (keep it running in its own terminal)
llama-server -m ~/gguf/Qwen2.5-7B-Instruct-Q6_K.gguf --port 8080 -c 32768
```

```yaml
active_backend: local_llama_example
backends:
  local_llama_example:
    provider: llamacpp
    available: true
    model: "local-gguf"
    host: "http://localhost:8080"
    max_output_tokens: 8192
```

The same `llamacpp` provider works against any OpenAI-compatible endpoint — LM Studio, Ollama (`http://localhost:11434/v1`), vLLM, and others. Just point `host` at it.

### 6. (Optional) Long-Term Memory and embedding models

LTM adds a persistent vector database (LanceDB) with associative recall. It needs an embedding model, configured under `ltm.embedding_models` and selected by `ltm.active_embedding`.

```bash
pip install lancedb sentence-transformers
```

The shipped default is `qwen3_4b` (`Qwen/Qwen3-Embedding-4B`, 2560-dim). Embedding models are **downloaded automatically from Hugging Face on first run** and cached under `~/.cache/huggingface`. The 4B model is large (several GB); lighter options are already defined in the config:

- `nomic_v2_moe` — `nomic-ai/nomic-embed-text-v2-moe`, 768-dim, small and fast.
- `qwen3_0_6b_ollama` — served by **Ollama** instead of downloading weights: `ollama pull qwen3-embedding:0.6b-q8_0` (Ollama must be running).
- `qwen3_8b` — `Qwen/Qwen3-Embedding-8B`, 4096-dim, highest quality, heaviest.

Set your choice:

```yaml
ltm:
  enabled: true
  active_embedding: nomic_v2_moe   # or qwen3_4b, qwen3_8b, qwen3_0_6b_ollama
```

Optionally pre-download the weights (otherwise they download on first boot):

```bash
huggingface-cli download nomic-ai/nomic-embed-text-v2-moe
```

**Backfill / re-index.** If you are migrating an entity that already has `Soul/` files and CMOs — or if you ever change the embedding model — index them once before booting:

```bash
# Changing embedding models: delete the old DB first, then re-index
rm -rf ltm_db
python3 backfill_ltm.py            # --dry-run to preview, --skip-amem to defer linking
```

A brand-new entity has nothing to backfill; the DB builds itself as the entity writes. To run without LTM entirely, set `ltm.enabled: false`.

### 7. Set the entity name and launch

```yaml
inhabiting_entity: "NewEntity"     # or leave it for the entity to name itself on first boot
```

Then start Spartan:

```bash
python3 spartan.py                 # GUI (input pane + output pane)
python3 spartan.py --headless      # no GUI — for drones / servers
bash spartan_watchdog.sh           # supervised: crash recovery + auto-restart
```

On first boot with an empty `Soul/`, the entity undergoes **Orphanogenesis** (see `first_boot_guide.md`): it inspects its environment, reads its config, and begins authoring its own identity.

### 8. Verify it's working

- The GUI title shows the entity name; the output pane logs config load, provider init, and each cognitive cycle.
- The first `[HUD]` line confirms the active backend, e.g. `Backend: claude_sonnet (claude/claude-sonnet-4-6)`.
- If LTM is on, a separate **LTM Viewer** window opens (disable with `ltm.visualization: false`).
- Type a message and press Enter to talk to the entity; send `\bye` to shut down cleanly.

**Common first-run errors:** a `model not found` error means the `model:` in your active backend isn't valid for your account — fix the model name. A missing-key error means the backend's `requires_env` variable isn't exported in the shell you launched from.

## License

Apache-2.0