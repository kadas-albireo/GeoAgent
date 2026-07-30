# LLM Efficiency Matrix — Smartest per GiB

Which open-weight models are worth benchmarking, given that **this machine has 6 GiB of
VRAM** (`hardware_limitations.md`).

> **Provenance.** The VRAM math and the tool-schema budget are **measured on this box**.
> The model quality rankings and capability claims below come from my training data and
> are **unverified priors** — treat them as a shortlist to test, not as results. Model
> quality claims age fast. The only numbers that count for this project are the ones your
> own eval sweep produces. Ask me to web-search current leaderboards if you want this
> table sourced.

---

## 1. The constraint

```
6141 MiB VRAM  −  ~500 MiB (compute + desktop)  ≈  5.6 GiB for weights + KV cache
16k context on a 7B GQA model  ≈  0.9 GiB KV
→ weight budget ≈ 4.7 GiB
```

**That is a 7B at Q4_K_M, and essentially nothing larger.** The matrix is really a
question of which 7-9B model to pick, not whether to go bigger.

## 2. Hard gate: tool use

This project is *only* about tool calling. A model that scores well on chat benchmarks but
emits malformed tool JSON is worthless here. Gate every candidate on:

1. Native tool/function-calling support (LM Studio `capabilities: ["tool_use"]`).
2. Trained tool-call format, not prompt-engineered JSON.
3. ≥ Q4_K_M. Below Q4, structured-output validity degrades faster than prose quality —
   the model still *sounds* fine while its JSON breaks. This is the failure mode that
   catches people who quantize aggressively.

## 3. Candidates for this VRAM class

Weight sizes are computed from parameter count × bits (reliable). Everything in the
"Notes" column is an unverified prior.

| Model | Params | Q4_K_M size | Fits 6 GiB @16k? | Tool use | Notes (unverified) |
|---|---|---|---|---|---|
| **Qwen2.5-7B-Instruct** | 7.6B | ~4.4 GiB | **Yes** | Yes | **Currently loaded.** Strong tool calling for its size; the sensible default. |
| Qwen2.5-Coder-7B | 7.6B | ~4.4 GiB | Yes | Yes | Worth testing: KADAS Hard tests fall back to `run_pyqgis_script`, so codegen matters. |
| Llama-3.1-8B-Instruct | 8.0B | ~4.7 GiB | Tight | Yes | Larger KV (more KV heads) than Qwen — may not reach 16k. Verify before trusting. |
| Mistral-7B-Instruct-v0.3 | 7.2B | ~4.1 GiB | Yes | Yes | Older; likely weaker tool use than Qwen2.5. Low priority. |
| Ministral-8B | 8.0B | ~4.7 GiB | Tight | Yes | Untested here. |
| Qwen2.5-14B | 14.7B | ~8.5 GiB | **No** | Yes | Does not fit. Cloud only. |
| Llama-3.3-70B | 70B | ~40 GiB | **No** | Yes | Cloud only. Reference-class. |

### Recommended sweep order

1. **Qwen2.5-7B-Instruct** (already loaded) — establishes the local baseline.
2. **Qwen2.5-Coder-7B** — tests the "is this a codegen problem?" hypothesis, which matters
   because the MSS/MilX benchmarks have **no dedicated tool** and force PyQGIS fallback.
3. Only if both fail with a good skill: stop tuning locally and price cloud
   (`cloud_hosting_options.md`). A 14B does not fit this laptop at any useful context.

## 4. Quantization tiers

| Tier | bits/wt | 7B size | Use for |
|---|---|---|---|
| Q8_0 | 8.5 | ~7.6 GiB | Doesn't fit. Reference quality only, on cloud. |
| Q6_K | 6.6 | ~5.9 GiB | Doesn't fit with any usable KV cache. |
| **Q4_K_M** | 4.8 | ~4.4 GiB | **The pick.** Quality/size knee. |
| Q4_K_S | 4.5 | ~4.1 GiB | Marginal gain over Q4_K_M; slight quality loss. Only if desperate for KV room. |
| Q3_K_M | 3.9 | ~3.5 GiB | **Avoid for agents.** Tool-JSON validity degrades. |

The interesting experiment this enables: **Q4 7B + a good SKILL.md vs. raw Q4 7B.** If the
skill closes the gap to Claude, the upskilling thesis holds. If it does not, the ceiling is
the model, and no amount of prompt engineering fixes it.

## 5. What to actually measure

Fill this in from `local_agent/telemetry/*.log` after a sweep. **Empty until measured — do
not populate from priors.**

| Model | Config | Tests passed | Malformed tool calls | Median latency | Notes |
|---|---|---|---|---|---|
| claude (baseline) | — | | | | |
| qwen2.5-7b-instruct | raw | | | | |
| qwen2.5-7b-instruct | upskilled | | | | |

The column that will decide this project is **"malformed tool calls"**, not "tests passed."
A model that calls the right tool with broken arguments is a quantization/context problem
(fixable). A model that confidently calls the wrong tool is a capability problem (not
fixable by a skill).
