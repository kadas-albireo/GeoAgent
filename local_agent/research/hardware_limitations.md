# Hardware Limitations & Context Budget

Framework for logging this machine's specs and deriving the **real** ceiling on model
size, quantization, and context length.

The headline finding is not about the model. It is that **the GeoAgent tool schemas,
not the prompts, consume the context window.** See [Context budget](#context-budget)
before tuning anything else.

---

## 1. Logged machine specs

Measured 2026-07-16 on the dev laptop. Reproduce with the commands in each row.

| Component | Value | Command |
|---|---|---|
| CPU | Intel Core Ultra 9 185H (16 cores / 22 threads) | `lscpu \| grep 'Model name'` |
| System RAM | 30 GiB total | `free -g` |
| dGPU | NVIDIA RTX 4050 **Laptop** | `nvidia-smi --query-gpu=name --format=csv` |
| **VRAM** | **6141 MiB (~6 GiB)** | `nvidia-smi --query-gpu=memory.total --format=csv` |
| iGPU | Intel Arc (Meteor Lake, `00:02.0`) | `lspci \| grep VGA` |
| Driver | 560.28.03 | `nvidia-smi --query-gpu=driver_version --format=csv` |

**6 GiB of VRAM is the binding constraint on this machine.** Everything below follows
from it. The 30 GiB of system RAM is nearly irrelevant for GPU inference: once you spill
into it, throughput collapses to CPU speeds (see [Offload](#4-offload-what-it-costs)).

> Re-run and update this table when the hardware changes. Do not reason from remembered
> numbers, they go stale silently.

---

## 2. VRAM budget model

Three things compete for the same 6141 MiB:

```
VRAM_total  =  weights  +  KV cache  +  compute buffers  +  desktop/display
```

- **Weights** — fixed by parameter count and quantization. See the formula below.
- **KV cache** — grows *linearly with context length*. The variable people forget.
- **Compute buffers** — activations, CUDA graphs, etc. Budget ~300-500 MiB.
- **Desktop** — the compositor and browser are on this GPU too. Budget a few hundred MiB.

### Weights

```
weight_bytes  ≈  n_params  ×  bits_per_weight / 8
```

For a 7B model:

| Quant | bits/weight | Weight size | Fits 6 GiB? |
|---|---|---|---|
| F16 | 16 | ~14.2 GiB | No |
| Q8_0 | 8.5 | ~7.6 GiB | No |
| Q6_K | 6.6 | ~5.9 GiB | No headroom for KV |
| **Q4_K_M** | **4.8** | **~4.4 GiB** | **Yes — the sweet spot here** |
| Q3_K_M | 3.9 | ~3.5 GiB | Yes, but quality drops sharply |

Q4_K_M is the standard quality/size knee: near-Q8 quality at ~55% the size. Below Q4,
instruction-following and especially **tool-call JSON validity** degrade fast, which is
exactly what this project measures. Do not go below Q4 for agent work.

### KV cache — the context tax

```
kv_bytes_per_token  =  2 (K and V)  ×  n_layers  ×  n_kv_heads  ×  head_dim  ×  bytes_per_elem
```

Worked for **qwen2.5-7b-instruct** (28 layers, 4 KV heads via GQA, head_dim 128, fp16):

```
2 × 28 × 4 × 128 × 2  =  57,344 bytes/token  ≈  56 KiB/token
```

**VERIFIED 2026-07-16.** LM Studio's `--estimate-only` gives its projection; `nvidia-smi`
gives the truth. They disagree, and the difference matters:

| Context | LM Studio estimate | Verdict |
|---|---|---|
| 12,288 | 5.12 GiB | fits |
| 16,384 | 5.33 GiB | fits |
| 20,480 | 5.53 GiB | fits |
| 24,576 | 5.74 GiB | fits |
| **32,768** | **6.15 GiB** | **estimate exceeds 6,141 MiB — yet it loads fine** |

The estimate slope confirms the formula: (6.15 − 5.12) GiB over 20,480 tokens ≈
**54 KiB/token**, within 4% of the 56 KiB/token predicted from the architecture. The
formula is sound.

**But the estimate is conservative.** qwen2.5-7b **actually loads at 32,768 and sits at
5,479 MiB (5.35 GiB)** — 0.8 GiB below the projection, and it served a real 22,053-token
prompt successfully. llama.cpp appears to allocate the KV cache lazily rather than
reserving the worst case up front.

> **Use `--estimate-only` as an upper bound, not a gate.** Treating its number as the real
> requirement would have you cap this machine at 16k when 32k demonstrably works.

### The `--gpu max` trap

**Do not pass `--gpu max`.** It reads like the safe choice — "keep the model fully GPU
resident, avoid the 10× CPU-offload penalty" — and it is actively harmful:

```bash
lms load qwen2.5-7b-instruct -c 32768 --gpu max -y   # FAILS: "Error loading model"
lms load qwen2.5-7b-instruct -c 32768 -y             # succeeds in 3.3s, 5,479 MiB
```

`--gpu max` overrides LM Studio's automatic offload planning and makes a borderline load
fail outright, with an opaque error that looks like a broken model. Omit the flag and let
LM Studio plan. This is encoded in `geoagent/core/lmstudio.py` (`gpu=None` default).

---

## 3. Context budget

**This is the section that matters.** Measured against the live `for_kadas()` agent on
2026-07-16. These are **real `cl100k_base` BPE counts, not estimates** (`tiktoken` is
installed in the py3.12 venv). Reproduce with:

```bash
~/.open_geoagent/venv_py3.12/bin/python local_agent/tests/context_budget.py
```

| Consumer | Tokens | Note |
|---|---|---|
| Tool schemas (62 tools, full surface) | **~10,583** | The dominant cost, by far |
| `KADAS_SYSTEM_PROMPT` (incl. terminal guidance) | ~2,161 | Fixed |
| `skills/skills_prompt.md` (all 5 skills bundled) | ~3,894 | **Grows with every skill added** |
| One *selected* skill (`skills/selector.py`) | ~700-880 | What the runner actually injects |
| **Full surface + prompt + whole bundle** | **~16,600** | |

At the **8,192** default this overflows by 52% before the user says anything, which is what
originally drove this investigation. **At 32,768 (now loaded) it comfortably fits:**

| Surface | Tools | Schemas | + system | vs 32,768 | Verdict |
|---|---|---|---|---|---|
| **`for_kadas()`** | **62** | ~10,583 | **~12,750** | **39%** | **Fits. Keep every tool.** |
| `for_kadas(fast=True)` | 41 | ~7,181 | ~9,350 | 29% | Fits, but unnecessary |

**Verified end-to-end 2026-07-16:** qwen2.5-7b at 32,768, handed **all 62 tools**, chose
correctly on 3/3 prompts (`list_project_layers`, `locate_and_zoom`, `add_osm_basemap`).
The premise that 62 tools would overwhelm a 7B is **not supported** on easy prompts. Hard
prompts are still an open question — that is what the benchmark exists to answer.

### Do not subset the tools

The earlier version of this document recommended cutting the surface to ~6 tools per task.
**That was wrong**, for two reasons:

1. **It solved an 8k problem that no longer exists.** At 32k the full surface is 39% of the
   window.
2. **Hardcoding a per-task tool list leaks the answer.** Handing a "list the layers" test
   exactly `[list_project_layers, get_project_state]` does not measure tool selection; the
   model cannot choose wrong. It measures argument filling while pretending to measure
   selection.

Retrieval is not removal. If the surface ever *does* need narrowing, the right pattern is
[Tool Search](https://www.anthropic.com/engineering/advanced-tool-use) /
[RAG-MCP](https://arxiv.org/abs/2505.03275) — retrieve from the full catalog so the model
keeps access to everything — not amputation.

### Prompt caching decides the architecture

Measured on this box with a stable ~16k prefix:

| call | prompt | latency |
|---|---|---|
| 1st (cold) | 16,025 | **13.62s** |
| 2nd (identical prefix) | 16,026 | **0.47s** |
| 4th (**changed** prefix) | 24,025 | **22.61s** |

llama.cpp caches a stable prefix and reuses it, ~29× faster. Consequence:

> **Per-turn dynamic tool retrieval would break the cache.** Changing the tool block
> invalidates the entire prefix, including history, forcing a full reprefill every turn.
> A static 62-tool prefix costs ~9-14s once, then ~0.5s.

So order the prompt cache-first:

```
[ STABLE  — cached ]  system prompt + all 62 tool definitions   (~12.7k)
[ VOLATILE — cheap ]  retrieved doc snippets + skill + query
```

Static content first, volatile last. Retrieve *documentation* into the tail; leave the
tool definitions alone. Observed in practice: 14.3s first turn, ~5s subsequent.

### What follows from this

1. **Load at 32,768, not the 8,192 default.** This is the single highest-value change, and
   it dissolves the problem the rest of this document was written to solve. `lms load
   qwen2.5-7b-instruct -c 32768 -y` (**no `--gpu` flag**). `geoagent/core/lmstudio.py`
   does this automatically.
2. **Keep all 62 tools.** They cost 39% of a 32k window and cache after the first turn.
3. **Skill bundling does not scale; skill *selection* does.** With one skill the bundle was
   673 tokens; with five it is **3,894**. Any single relevant skill is ~800. Injecting the
   whole bundle spends budget teaching the model about MilX when it was asked about
   coordinates, and the irrelevant guidance dilutes tool choice on top of costing tokens.
   **Select, do not bundle.** Bundling is the fallback for an unmatched prompt only. This
   applies to *documentation and skills* — the volatile tail — not to tool definitions.
4. **Context degradation is real but was over-weighted here.** Recall degrades with input
   length even when the evidence is well placed
   ([context rot](https://arxiv.org/abs/2307.03172)). But this model retrieved a needle
   from a **22,053-token** prompt on this box, so the earlier "treat 60% as the ceiling"
   heuristic was too conservative for a simple lookup. It may still bite on *tool
   selection*, which is a harder task than recall. Let the eval telemetry arbitrate, not
   this doc.

---

## 4. Offload: what it costs

When a model does not fit, LM Studio silently offloads layers to CPU rather than failing.
Watch for this — it looks like "working, but mysteriously slow."

| Config | Throughput (order of magnitude) |
|---|---|
| Fully on GPU | ~40-60 tok/s |
| A few layers offloaded | ~10-15 tok/s |
| Mostly CPU | ~2-4 tok/s |

An agent turn with 10 tool calls at 3 tok/s is minutes of wall-clock. If evals feel slow,
check `n_gpu_layers` and confirm the whole model is resident before blaming the model.

> Throughputs are illustrative magnitudes, not measurements from this machine. Fill in real
> numbers from the eval telemetry (`latency_ms`) once you have run a benchmark sweep.

---

## 5. Verdict for this machine

- **Ceiling: a 7B-class model at Q4_K_M at the full 32k context.** Verified: 5,479 MiB of
  6,141, fully GPU-resident, serving 22k-token prompts. That is what 6 GiB buys, and it is
  more than the estimator suggests.
- A 14B at Q4 (~8.5 GiB) does **not** fit. Neither does a 7B at Q8.
- The full 62-tool KADAS agent **fits comfortably** (39% of the window) and selects
  correctly on easy prompts. There is no context emergency here.
- If the 7B cannot drive KADAS reliably *with the full tool surface and a good skill*, the
  answer is **not** a bigger local model on this laptop. It is cloud GPU
  (see `cloud_hosting_options.md`) or accepting Claude as the production path.

## Checklist for a new machine

- [ ] Record the specs table in §1 from the actual commands.
- [ ] Compute the weight size for the target model/quant (§2).
- [ ] Compute KV bytes/token from the model's real config (`n_layers`, `n_kv_heads`, `head_dim`).
- [ ] Get LM Studio's projection: `lms load <model> -c <ctx> --estimate-only -y`.
- [ ] **Then load it and measure reality** (`nvidia-smi`). The estimate ran 0.8 GiB high
      here; trusting it would have capped this machine at 16k when 32k works.
- [ ] **Never pass `--gpu max`** — it overrides LM Studio's planner and fails borderline loads.
- [ ] Measure the tool-schema cost with `local_agent/tests/context_budget.py`.
- [ ] Verify no CPU offload (`nvidia-smi` during a run; watch for ~3 tok/s).
