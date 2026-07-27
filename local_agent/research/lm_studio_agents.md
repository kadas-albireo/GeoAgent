# LM Studio — Local Agent Endpoints

How to point GeoAgent at a locally served model, and what this machine currently serves.

LM Studio exposes an **OpenAI-compatible** REST API, which is why GeoAgent can drive it
through the existing `litellm` provider with no new code.

---

## 1. Live endpoint (verified 2026-07-16)

Base URL: `http://localhost:1234/v1`

```bash
curl -s http://localhost:1234/v1/models          # OpenAI-compatible listing
curl -s http://localhost:1234/api/v0/models      # LM Studio native — richer metadata
```

The native `/api/v0/models` route is the more useful one: it reports quantization,
context length, and load state, which the OpenAI-compatible route omits.

Currently served:

| Model | Type | Quant | Arch | Max ctx | Loaded ctx | Tool use | State |
|---|---|---|---|---|---|---|---|
| **`qwen2.5-7b-instruct`** | LLM | Q4_K_M | qwen2 | 32,768 | **8,192** | **yes** | loaded |
| `text-embedding-nomic-embed-text-v1.5` | embedding | Q4_K_M | nomic-bert | 2,048 | — | no | not-loaded |

Two things to notice:

- **`capabilities: ["tool_use"]`** — non-negotiable for this project. A model without it
  cannot drive GeoAgent at all; it will emit prose describing the tool call instead of
  calling it. Check this field before benchmarking any new model.
- **`loaded_context_length: 8192` ≠ `max_context_length: 32768`.** The loaded value is
  what you actually get. It is a default, and it is **too small for the KADAS tool
  surface** — see `hardware_limitations.md` §3. Raise it to 16,384 in the model's load
  settings (Developer tab → context length → reload).

---

## 2. Wiring GeoAgent to it

GeoAgent resolves providers in `geoagent/core/model.py`. The `litellm` branch reads
`LITELLM_BASE_URL` / `LITELLM_MODEL` / `LITELLM_API_KEY`, or takes them from
`GeoAgentConfig`.

The `openai/` prefix on the model id is a **LiteLLM routing directive**, not part of the
model name: it tells LiteLLM "speak the OpenAI protocol to this endpoint." Without it,
LiteLLM cannot infer the dialect and errors out.

### Via environment

```bash
export LITELLM_BASE_URL="http://localhost:1234/v1"
export LITELLM_MODEL="openai/qwen2.5-7b-instruct"
export LITELLM_API_KEY="lm-studio"   # LM Studio ignores the value, but a value must exist
```

### Via config (what the eval runner does)

```python
from geoagent.core.config import GeoAgentConfig

config = GeoAgentConfig(
    provider="litellm",
    model="openai/qwen2.5-7b-instruct",
    litellm_base_url="http://localhost:1234/v1",
    client_args={"api_key": "lm-studio"},
)
agent = factory.for_kadas(iface, project, config=config, fast=True)
```

`api_key` must be a non-empty string. LM Studio never validates it, but the OpenAI client
library refuses to construct without one.

---

## 3. Adding a model to the bench

1. **Check `tool_use`** in `/api/v0/models`. No tool use, no benchmark.
2. **Check it fits.** Weights + KV cache ≤ ~5.3 GiB on this box (`hardware_limitations.md` §2).
3. **Set the loaded context to 16,384**, not the 8,192 default.
4. **Confirm no CPU offload** — `nvidia-smi` during a turn. Offload is silent and 10× slow.
5. **Register it** in `local_agent/tests/run_evals.py` (`AGENT_CONFIGS`), then run the sweep.

## 4. Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| `Connection refused` on :1234 | Server not started | LM Studio → Developer → Start Server |
| Model replies in prose, never calls a tool | Model lacks `tool_use`, or the prompt overflowed and the schemas were truncated | Check capabilities; check `context_budget.py` |
| Truncated / invalid tool-call JSON | Context overflow, or quant below Q4 | Raise ctx, subset tools, use ≥Q4_K_M |
| Mysteriously ~3 tok/s | Layers offloaded to CPU | Reduce ctx or quant until fully GPU-resident |
| `api_key` client error | Empty API key string | Set any non-empty value |

## 5. Why LiteLLM and not the `openai` provider

Both would work against an OpenAI-compatible endpoint. `litellm` is preferable here
because it normalizes tool-call formatting quirks across local backends (LM Studio,
Ollama, vLLM), so swapping the serving layer does not change GeoAgent code. The cost is
one extra dependency and a slightly noisier stack trace. If you standardize on LM Studio
permanently, the `openai` provider with a `base_url` override is the leaner path.
