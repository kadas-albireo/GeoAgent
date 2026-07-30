# KADAS GeoAgent: Running the AI on your own computer

## What you need

- 8 GB of graphics memory (VRAM) is comfortable. 6 GB works.
- About 5 GB of free disk space.
- Windows or Linux.
- Without a graphics card it runs on the processor, but more slowly.

---

## Step 1: Install LM Studio

LM Studio is a free application that runs AI models on your computer.

1. Go to **<https://lmstudio.ai>** and download the version for your system.
2. Install it like any other application.
3. Open LM Studio once so it finishes setting itself up.

## Step 2: Turn on the command-line helper

GeoAgent starts and stops the model for you, but it needs LM Studio's helper
tool to do that. This is the only technical step in this guide.

Open a terminal:
- **Windows:** press the Start key, type `powershell`, press Enter
- **Linux:** press `Ctrl+Alt+T`

Type this and press Enter:

```
lms bootstrap
```

If it reports success, you are done with this step.

> **If it says "command not found":** open LM Studio, go to **Developer** (or
> **Settings**) and look for an option like *"Install `lms` CLI"* or *"Enable
> command line tool"*. Turn it on, then close and reopen the terminal and try
> again.

## Step 3: Download a model

Use `qwen2.5-7b-instruct`. GeoAgent needs a model that can call map tools. Most
local models cannot, and GeoAgent refuses those. Qwen 2.5 7B Instruct is the
smallest model verified to handle the full tool set.

1. In LM Studio click the **magnifying glass** (Search / Discover).
2. Search for `qwen2.5-7b-instruct`.
3. Choose a **Q4_K_M** version if offered. It is the best balance of size and
   quality.
4. Click **Download** and wait (about 4.7 GB).

You do **not** need to load or start it. GeoAgent does that for you.

## Step 4: Point GeoAgent at it

1. In KADAS, open the GeoAgent **Settings** panel.
2. Go to the **Model** tab.
3. Set **Provider** to **`lmstudio`**.
4. Leave the model box empty. Empty means "use whatever LM Studio has", which is
   what you want.
5. Leave the API key box empty. A local model does not need one.
6. Click **Save**.

## Step 5: Turn on Plan-first reasoning (recommended)

In the GeoAgent chat panel, tick **Plan-first reasoning**. It makes the model
write a short plan before acting, which improves results on smaller models. Leave
it off when using Claude.

## Step 6: Try it

In the GeoAgent panel, type:

```
Load the swisstopo aerial imagery layer
```

The first question is slow while GeoAgent starts LM Studio and loads the model
into memory. Later questions are faster.

---

## Good to know

- Do not start LM Studio manually. GeoAgent starts the server and loads the model each time.
- The model unloads itself when idle.
- The first question after a break is slow because the model has to reload. This is normal.
- Do not set LM Studio's GPU offload to "max". On a 6 GB card this makes loading fail. Keep the default.

---

## Troubleshooting

| What you see | What to do |
|---|---|
| "LM Studio CLI ('lms') not found" | Step 2 did not complete. Redo it, then restart KADAS. |
| "Model does not support tools" | You picked a model that cannot call tools. Use `qwen2.5-7b-instruct`. |
| Nothing happens on the first question | Normal. The model is loading. |
| "Error loading model" | Not enough graphics memory. In LM Studio, pick a smaller download (Q4 instead of Q8), and make sure GPU offload is **not** set to max. |
| Answers are slow or confused | Expected for a local model. Turn on **Plan-first reasoning** (Step 5), and keep requests to one step at a time. |
| It won't use the map tools | Confirm the model is `qwen2.5-7b-instruct`. Smaller models often ignore tools. |

### Switching back to Claude

Open **Settings → Model**, set **Provider** back to `anthropic`, and enter your
key as in [INSTALL.md](INSTALL.md) Part 3. You can switch back and forth freely.