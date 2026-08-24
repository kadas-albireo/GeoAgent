# KADAS GeoAgent — Running the AI on your own computer

This is the alternative to [INSTALL.md](INSTALL.md) Part 3. Instead of using
Claude over the internet, the AI runs entirely on your machine.

| | Claude (online) | Local model |
|---|---|---|
| Cost | A few EUR/month | Free |
| Privacy | Questions sent to Anthropic | **Nothing leaves your computer** |
| Internet | Required | Only for the one-time download |
| Speed | Fast | Slower |
| Capability | High | **Noticeably weaker** |

**Be realistic about the trade-off.** A local model handles straightforward
requests ("load the aerial imagery", "zoom to Bern") well. Multi-step requests
("buffer this layer, clip it to the DTM, then tell me the maximum elevation") are
where it struggles. If your work is sensitive or offline, this is the right
choice — otherwise Claude will frustrate you less.

---

## What you need

- **8 GB of graphics memory (VRAM) is comfortable. 6 GB works.**
  Our reference machine has 6 GB and runs the recommended model at full context.
- About 5 GB of free disk space.
- Windows or Linux.

No graphics card? It will still run using the processor, but expect to wait
30 seconds or more per answer.

---

## Step 1 — Install LM Studio (5 minutes)

LM Studio is a free application that runs AI models on your computer.

1. Go to **<https://lmstudio.ai>** and download the version for your system.
2. Install it the same way you would any other application.
3. Open LM Studio once so it finishes setting itself up.

## Step 2 — Turn on the command-line helper (1 minute)

GeoAgent starts and stops the model for you automatically, but it needs LM
Studio's helper tool to do that. **This is the only technical step in this guide.**

Open a terminal:
- **Windows:** press the Start key, type `powershell`, press Enter
- **Linux:** press `Ctrl+Alt+T`

Type this and press Enter:

```
lms bootstrap
```

If it reports success, you are done with this step.

> **If it says "command not found":** open LM Studio, go to **Developer** (or
> **Settings**) and look for an option like *"Install `lms` CLI"* / *"Enable
> command line tool"*. Turn it on, then close and reopen the terminal and try
> again.

## Step 3 — Download a model (10 minutes, mostly waiting)

**Use `qwen2.5-7b-instruct`.** This matters more than it sounds: GeoAgent works by
letting the AI call map tools, and **most local models cannot call tools at all**.
GeoAgent will refuse a model that lacks this ability rather than fail
mysteriously. Qwen 2.5 7B Instruct is the smallest model we have verified handles
the full GeoAgent tool set correctly.

1. In LM Studio click the **magnifying glass** (Search / Discover).
2. Search for `qwen2.5-7b-instruct`.
3. Choose a **Q4_K_M** version if offered — it is the best size/quality balance.
4. Click **Download** and wait (about 4.7 GB).

You do **not** need to load or start it. GeoAgent does that for you.

## Step 4 — Point GeoAgent at it (1 minute)

1. In KADAS, open the GeoAgent **Settings** panel.
2. Go to the **Model** tab.
3. Set **Provider** to **`lmstudio`**.
4. **Leave the model box empty.** Empty means "use whatever LM Studio has" —
   which is what you want.
5. **Leave the API key box empty.** A local model does not need one.
6. Click **Save**.

## Step 5 — Turn on Plan-first reasoning (recommended)

In the GeoAgent chat panel, tick **Plan-first reasoning**.

This makes the AI write out a short plan before acting. It adds a second or two
per question but **markedly improves smaller models** — it is the single most
useful setting for local use. (Leave it off when using Claude; it is unnecessary
there.)

## Step 6 — Try it

In the GeoAgent panel, type:

```
Load the swisstopo aerial imagery layer
```

The first question takes **20–60 seconds** — GeoAgent is starting LM Studio and
loading the model into memory. Later questions are much faster.

---

## Good to know

**You do not need to start LM Studio manually.** GeoAgent starts the server,
loads the model, and sets it up correctly each time. Just use KADAS.

**The model unloads itself when idle** so it does not hold your graphics card
hostage after you have finished.

**Your first question after a break will be slow again** because the model has to
reload. This is normal.

**Do not change LM Studio's GPU offload setting to "max".** On a 6 GB card this
makes loading *fail*. The default setting is correct, and GeoAgent relies on it.

---

## Troubleshooting

| What you see | What to do |
|---|---|
| "LM Studio CLI ('lms') not found" | Step 2 did not complete. Redo it, then restart KADAS. |
| "Model does not support tools" | You picked a model that cannot call tools. Use `qwen2.5-7b-instruct`. |
| Nothing happens for a minute on the first question | Normal — the model is loading. |
| "Error loading model" | Not enough graphics memory. In LM Studio, pick a smaller download (Q4 instead of Q8), and make sure GPU offload is **not** set to max. |
| Answers are slow or confused | Expected for a local model. Turn on **Plan-first reasoning** (Step 5), and keep requests to one step at a time. |
| It won't use the map tools | Confirm the model is `qwen2.5-7b-instruct`; smaller models often ignore tools. |

### Switching back to Claude

Open **Settings → Model**, set **Provider** back to `anthropic`, and enter your
key as in [INSTALL.md](INSTALL.md) Part 3. You can switch back and forth freely.
