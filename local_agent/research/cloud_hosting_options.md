# Cloud Hosting Options for Local-Class LLMs

When 6 GiB of laptop VRAM is the ceiling (`hardware_limitations.md`), cloud GPU is how you
test models that do not fit. This is the decision framework and the provisioning recipe.

> **Provenance.** GPU **pricing and availability are not verified** — they move weekly and
> vary by region and spot market. Every price below is a rough order of magnitude from my
> training data, marked as such. **Check the provider's live pricing page before committing.**
> The VRAM requirements and the architecture guidance are sound; the dollar figures are not
> quotable. Ask me to web-search current rates if you need real numbers.

---

## 1. First: do you actually need this?

Cloud GPU is worth it only for a specific question. Before provisioning, note that:

- **Renting a GPU to run a 7B is pointless.** Your laptop already does that. Cloud earns
  its cost only for models that *cannot* fit locally (14B+, 70B).
- **If the goal is "best answers," Claude is already the baseline** and needs no GPU.
- The real question cloud answers is: **"is the local ceiling a size problem?"** If Qwen-7B
  fails a benchmark and Qwen-14B passes it, size is the issue and cloud/bigger hardware is
  the path. If 14B fails too, the problem is the tool surface or the skill, and no GPU
  spend fixes it.

Run the local sweep first. Provision cloud only to test a specific size hypothesis.

## 2. VRAM required by model class

This drives GPU selection. Weights at Q4_K_M + KV cache at 16k, plus ~15% headroom:

| Model class | Weights (Q4) | Needs | Cheapest sane GPU |
|---|---|---|---|
| 7-8B | ~4.5 GiB | ~8 GiB | RTX 4060 / T4 / A10 |
| 14B | ~8.5 GiB | ~14 GiB | RTX 4090 / A10G / L4 |
| 32B | ~19 GiB | ~28 GiB | A100 40G / RTX 6000 |
| 70B | ~40 GiB | ~56 GiB | A100 80G / H100 |

## 3. Provider comparison

| Provider | Model | Rough $/hr (**unverified**) | Best for | Watch out for |
|---|---|---|---|---|
| **Vast.ai** | Marketplace of consumer GPUs | 4090 ~$0.30-0.60 | **Cheapest experimentation** | Unvetted hosts; variable reliability; data privacy on strangers' machines |
| **RunPod** | Managed pods + serverless | 4090 ~$0.40-0.70; A100 ~$1.50-2.00 | **Best DX for this project** | Cold starts on serverless; regional scarcity |
| **Exoscale** | EU cloud (CH-based) | A40-class, hourly | **Swiss/EU data residency** | Smaller GPU catalogue; less LLM-specific tooling |
| **AWS** | `g5` (A10G), `p4d` (A100) | g5.xlarge ~$1.00; p4d ~$32 | Enterprise/compliance | Most expensive; quota requests take days |

### Why Exoscale is worth a look despite the thin catalogue

KADAS is a **swisstopo/Swiss-government-oriented** product. If eval data or prompts ever
touch non-public Swiss geodata, a Swiss-hosted GPU under Swiss jurisdiction is not a
nice-to-have, it is the whole reason to avoid Vast.ai. **Do not put sensitive geodata on a
Vast.ai marketplace box.** For this project's public swisstopo/OSM benchmarks it does not
matter — but the moment it does, that constraint dominates price.

## 4. Provisioning recipe (vLLM, provider-agnostic)

vLLM is the right server here: it is OpenAI-compatible, so GeoAgent reaches it via the
**same `litellm` config as LM Studio** — only the base URL changes.

```bash
pip install vllm

vllm serve Qwen/Qwen2.5-14B-Instruct \
  --dtype auto \
  --max-model-len 16384 \
  --gpu-memory-utilization 0.90 \
  --enable-auto-tool-choice \
  --tool-call-parser hermes \
  --api-key "$VLLM_API_KEY"
```

`--enable-auto-tool-choice` and `--tool-call-parser` are **mandatory** for this project.
Without them vLLM serves the model but never emits structured tool calls, and every
benchmark fails for a reason that has nothing to do with the model. The parser must match
the model family (`hermes` for Qwen, `llama3_json` for Llama-3.x).

Never expose the port publicly without an API key and an SSH tunnel or firewall rule:

```bash
ssh -N -L 8000:localhost:8000 user@<pod-ip>
```

Then GeoAgent needs no code change:

```bash
export LITELLM_BASE_URL="http://localhost:8000/v1"
export LITELLM_MODEL="openai/Qwen/Qwen2.5-14B-Instruct"
export LITELLM_API_KEY="$VLLM_API_KEY"
```

## 5. Latency trade-off

This is the part that surprises people running an *interactive* KADAS agent.

| Setup | Network RTT | Effect on an agent turn |
|---|---|---|
| Local (LM Studio) | ~0 ms | Fast per call; slow generation on 6 GiB |
| Cloud, same region | ~10-30 ms | Negligible |
| Cloud, cross-continent | ~100-150 ms | **Multiplied by every tool call** |

An agent turn is not one request. A 10-tool-call KADAS turn makes ~11 round trips, so
150 ms of RTT silently adds ~1.7 s. A big cloud GPU can generate far faster than the laptop
and still *feel* slower if it is a continent away. **Pick a region near the operator, not
near the cheapest GPU** — and for Swiss users that usually favours EU regions anyway.

## 6. Cost discipline

- **Idle GPUs bill.** Terminate, don't stop — stopped instances often still bill storage.
- Set a spend cap on day one.
- Spot/interruptible is fine for batch eval sweeps, bad for an interactive session.
- Snapshot the model to a volume; re-downloading a 40 GiB checkpoint on every boot costs
  more in GPU-hours than the volume does.

## 7. Decision

```
Does the benchmark fail locally on Qwen-7B + skill?
├── No  → done. Ship the local model. No cloud needed.
└── Yes → Does it fail on Claude too?
    ├── Yes → the benchmark, tool surface, or skill is wrong. Fix that. No GPU spend.
    └── No  → is the gap plausibly about model size?
        ├── Yes → rent a 4090/A100 for an afternoon, test 14B/32B, decide from data.
        └── No  → it's the tool surface or the skill. Fix that. No GPU spend.
```

The trap this avoids: renting an A100 because the local model is disappointing, when the
actual cause is that **62 tool schemas overflow the context window** (which is what is
happening on this machine today — see `hardware_limitations.md` §3). Fix the context
budget before you spend a franc.
