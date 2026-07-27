# KADAS GeoAgent — Installation Guide

GeoAgent adds an AI assistant panel to KADAS. You can ask it to do things in plain
language — "load the aerial imagery", "draw a 500 m circle around Bern", "how far
is it to Zurich?" — and it operates the map for you.

**You do not need any programming knowledge to follow this guide.**

- Time required: about 15 minutes
- You need: KADAS Albireo 2 installed, an internet connection, and a payment card
  (for the AI account, typically a few euros a month)

> **Prefer not to use an online AI service, or need to work offline?**
> Skip to [LOCAL_MODEL.md](LOCAL_MODEL.md) and run the AI on your own computer
> instead. It is free and private, but slower and less capable.

---

## Part 1 — Install the plugin (5 minutes)

The same file works on both Windows and Linux.

### Step 1. Open KADAS

Start KADAS Albireo 2 as you normally would.

### Step 2. Open the plugin installer

From the menu bar choose **Plugins → Manage and Install Plugins…**

### Step 3. Install from the ZIP file

1. In the window that opens, click **Install from ZIP** on the left.
2. Click the **…** button and select the file you were given:
   `kadas_geoagent-0.1.0.zip`
3. Click **Install Plugin**.
4. If a security warning appears, choose **Yes** / **Install anyway** — this
   appears for any plugin not downloaded from the public plugin shop.

You should see *"Plugin installed successfully"*.

### Step 4. Restart KADAS

Close KADAS completely and open it again. **This step is required** — the plugin
will not appear until you do.

### Step 5. Check it worked

You should now see a **GeoAgent** button in the KADAS toolbar. Click it and a
panel opens on the right-hand side.

It will say something like *"GeoAgent dependencies are not installed"*. That is
expected — Part 2 fixes it.

---

## Part 2 — Install the AI components (5 minutes)

The plugin needs some extra software components. It downloads them for you.

1. In the GeoAgent panel, open **Settings** (or **Plugins → GeoAgent → Settings**).
2. Go to the **Dependencies** tab.
3. Click **Install Dependencies**.
4. Wait. A progress bar runs for **2–10 minutes** depending on your connection.
   It is normal for it to pause on some items.
5. When it finishes, **restart KADAS again**.

> **If it fails:** you are most likely behind a company firewall or proxy. Note
> the error message shown and send it to your IT contact or to us — this step
> downloads from `pypi.org`, which some corporate networks block.

---

## Part 3 — Create an AI account and get your key (5 minutes)

GeoAgent needs an account with an AI provider. We recommend **Claude**, made by
Anthropic. **You pay Anthropic directly for what you use** — GeoAgent adds no
charge, and we never see your key.

Typical cost for normal daily use is **a few euros per month**. You can set a hard
spending limit so you can never be surprised by a bill.

### Step 1. Create the account

1. Go to **<https://console.anthropic.com>**
2. Click **Sign up** and register with your email address.
3. Confirm your email when the message arrives.

> Note: this is the *developer console*, which is different from the
> claude.ai chat website. A claude.ai subscription does **not** work here — you
> need this separate console account.

### Step 2. Add credit

1. In the left-hand menu click **Billing** (sometimes under **Settings**).
2. Click **Add credits** or **Set up billing** and enter your card details.
3. Add a small starting amount — **5 or 10 EUR is plenty** to begin with.

**Strongly recommended:** while you are on this page, find **Spend limits** (or
**Usage limits**) and set a monthly cap, for example 20 EUR. This is your safety
net.

### Step 3. Create your key

1. In the left-hand menu click **API keys**.
2. Click **Create key**.
3. Give it a name you will recognise, for example `KADAS GeoAgent`.
4. Click **Create**.
5. A long code appears, starting with `sk-ant-`.
   **Copy it now and keep the window open** — you cannot view it again after
   closing. If you lose it, simply delete that key and create another.

> **Treat this code like a password.** Anyone who has it can spend your credit.
> Do not email it, put it in a shared document, or paste it into a chat.

### Step 4. Enter the key into GeoAgent

1. Back in KADAS, open the GeoAgent **Settings** panel.
2. Go to the **Model** tab.
3. Set **Provider** to **anthropic**.
4. Paste your key into the **API key** box.
5. Click **Save**.

---

## Part 4 — Check everything works

In the GeoAgent panel, type:

```
Load the swisstopo aerial imagery layer
```

and press Enter. Within a few seconds the imagery should appear on your map.

Try a few more:

| Ask it | What should happen |
|---|---|
| `Draw a red circle 500 m around Bern` | A translucent red circle appears |
| `How far and what bearing from Bern to Zurich?` | It replies with distance and azimuth |
| `Add a route from Bern to Thun to Interlaken` | A route line is drawn |

**That's it — you're set up.**

---

## Troubleshooting

| What you see | What to do |
|---|---|
| No GeoAgent button after installing | Restart KADAS. If still missing, redo Part 1. |
| "Dependencies not installed" | Do Part 2, then restart KADAS. |
| "No API key configured" | Do Part 3 Step 4. |
| "Authentication error" / "invalid x-api-key" | The key was copied incompletely. Create a new key and paste the whole thing. |
| "Credit balance too low" | Add credit at <https://console.anthropic.com> under Billing. |
| It answers questions but won't change the map | Check the **Permissions** setting in the panel isn't set to a restricted profile. |
| Warning about invalid layers on startup | Unrelated to GeoAgent — a KADAS data file is missing. Contact us. |

### Getting help

If you are stuck, switch the panel to **Developer mode** using the button at the
top, reproduce the problem, then send us:

- the message shown in the panel, and
- the log file:
  - **Linux:** `~/.kadas/agent_execution.log`
  - **Windows:** `C:\Users\<your name>\.kadas\agent_execution.log`

---

## Frequently asked questions

**Is my map data sent to the AI company?**
Your questions and information *about* your layers (names, coordinates) are sent
to Anthropic so it can answer. Your actual data files are not uploaded. If this
is unacceptable for your work, use [LOCAL_MODEL.md](LOCAL_MODEL.md) instead —
nothing leaves your computer.

**How much will it cost?**
You pay Anthropic per question, typically a fraction of a cent each. Normal daily
use runs a few euros a month. Set a spend limit (Part 3, Step 2) to be certain.

**Can several people share one key?**
Technically yes, but it is better to give each person their own key so you can
see who used what and disable one without affecting the others.

**Does it work without internet?**
Not with Claude. See [LOCAL_MODEL.md](LOCAL_MODEL.md) for the offline option.
