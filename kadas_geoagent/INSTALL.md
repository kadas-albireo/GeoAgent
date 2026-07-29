# KADAS GeoAgent: Installation Guide

GeoAgent adds an AI assistant panel to KADAS. You ask it to do things in plain
language, for example "load the aerial imagery", "draw a 500 m circle around
Bern", or "how far is it to Zurich?", and it operates the map for you.

You do not need any programming knowledge to follow this guide.

- Time required: about 15 minutes.
- You need: KADAS Albireo, an internet connection, and a payment card for the AI
  account (usually a few euros a month).

This plugin works on both KADAS Albireo 2 and KADAS Albireo 3. It detects which
version you are running and adapts automatically, so there is nothing to
configure for your version.

If you would rather not use an online AI service, or you need to work offline,
see [LOCAL_MODEL.md](LOCAL_MODEL.md). Running the AI on your own computer is free
and private, but slower and less capable.

## Part 1: Install the plugin

The same file works on Windows and Linux.

### Step 1. Open KADAS

Start KADAS Albireo as you normally would.

### Step 2. Open the plugin installer

From the menu bar, choose Plugins, then "Manage and Install Plugins".

If your KADAS build has no such menu, skip to "Installing without the plugin
manager" below.

### Step 3. Install from the ZIP file

1. In the window that opens, click "Install from ZIP" on the left.
2. Click the "..." button and select the file you were given, named something
   like `kadas_geoagent-0.2.0.zip`.
3. Click "Install Plugin".
4. If a security warning appears, choose "Yes" or "Install anyway". This appears
   for any plugin not downloaded from the public plugin shop.

You should see "Plugin installed successfully".

### Step 4. Restart KADAS

Close KADAS completely and open it again. This step is required. The plugin will
not appear until you do.

### Step 5. Check it worked

You should now see a GeoAgent button in the KADAS toolbar. Click it and a panel
opens on the right-hand side.

It will say something like "GeoAgent dependencies are not installed". That is
expected. Part 2 fixes it.

### Installing without the plugin manager

Some KADAS builds do not have the "Manage and Install Plugins" menu. In that
case you install the plugin by copying its folder into the KADAS plugins
directory by hand.

1. Unzip the file you were given. You get a folder named `kadas_geoagent`.
2. Copy that whole `kadas_geoagent` folder into the KADAS plugins directory for
   your operating system:

   - Windows:
     `C:\Users\<your name>\AppData\Roaming\Kadas\Kadas\profiles\default\python\plugins\`
   - Linux:
     `~/.local/share/Kadas/Kadas/profiles/default/python/plugins/`

   `AppData` is a hidden folder on Windows. To reach it, open a File Explorer
   window, type `%APPDATA%` into the address bar, and press Enter. That opens the
   `Roaming` folder, from which you continue to `Kadas\Kadas\profiles\default`.

   If any folder in that path does not exist yet, create it. The final result
   should be a folder ending in
   `...\profiles\default\python\plugins\kadas_geoagent` that contains a file
   called `metadata.txt`.

3. Restart KADAS.
4. If the GeoAgent button still does not appear, open Plugins, then the plugin
   list, and make sure "KADAS GeoAgent" is enabled.

Note: if you use a KADAS profile other than `default`, replace `default` in the
paths above with your profile name.

## Part 2: Install the AI components

The plugin needs some extra software components. It downloads them for you.

1. In the GeoAgent panel, open Settings (or Plugins, then GeoAgent, then
   Settings).
2. Go to the Dependencies tab.
3. Click "Install Dependencies".
4. Wait. A progress bar runs for 2 to 10 minutes depending on your connection.
   It is normal for it to pause on some items.
5. When it finishes, restart KADAS again.

If it fails, you are most likely behind a company firewall or proxy. Note the
error message shown and send it to your IT contact or to us. This step downloads
from `pypi.org`, which some corporate networks block.

## Part 3: Create an AI account and get your key

GeoAgent needs an account with an AI provider. We recommend Claude, made by
Anthropic. You pay Anthropic directly for what you use. GeoAgent adds no charge,
and we never see your key.

Typical cost for normal daily use is a few euros per month. You can set a hard
spending limit so you are never surprised by a bill.

### Step 1. Create the account

1. Go to https://console.anthropic.com
2. Click "Sign up" and register with your email address.
3. Confirm your email when the message arrives.

Note: this is the developer console, which is different from the claude.ai chat
website. A claude.ai subscription does not work here. You need this separate
console account.

### Step 2. Add credit

1. In the left-hand menu, click Billing (sometimes under Settings).
2. Click "Add credits" or "Set up billing" and enter your card details.
3. Add a small starting amount. 5 or 10 EUR is plenty to begin with.

We strongly recommend that while you are on this page you find "Spend limits" (or
"Usage limits") and set a monthly cap, for example 20 EUR. This is your safety
net.

### Step 3. Create your key

1. In the left-hand menu, click "API keys".
2. Click "Create key".
3. Give it a name you will recognise, for example `KADAS GeoAgent`.
4. Click "Create".
5. A long code appears, starting with `sk-ant-`. Copy it now and keep the window
   open. You cannot view it again after closing. If you lose it, delete that key
   and create another.

Treat this code like a password. Anyone who has it can spend your credit. Do not
email it, put it in a shared document, or paste it into a chat.

### Step 4. Enter the key into GeoAgent

1. Back in KADAS, open the GeoAgent Settings panel.
2. Go to the Model tab.
3. Set Provider to "anthropic".
4. Paste your key into the "API key" box.
5. Click Save.

## Part 4: Check everything works

In the GeoAgent panel, type:

```
Load the swisstopo aerial imagery layer
```

and press Enter. Within a few seconds the imagery should appear on your map.

Try a few more:

- "Draw a red circle 500 m around Bern" should draw a translucent red circle.
- "How far and what bearing from Bern to Zurich?" should reply with distance and
  azimuth.
- "Add a route from Bern to Thun to Interlaken" should draw a route line.

That is it. You are set up.

## Troubleshooting

- No GeoAgent button after installing: restart KADAS. If it is still missing,
  redo Part 1.
- "Dependencies not installed": do Part 2, then restart KADAS.
- "No API key configured": do Part 3, Step 4.
- "Authentication error" or "invalid x-api-key": the key was copied
  incompletely. Create a new key and paste the whole thing.
- "Credit balance too low": add credit at https://console.anthropic.com under
  Billing.
- It answers questions but will not change the map: check that the Permissions
  setting in the panel is not set to a restricted profile.
- Warning about invalid layers on startup: this is unrelated to GeoAgent. A KADAS
  data file is missing. Contact us.

### Getting help

If you are stuck, switch the panel to Developer mode using the button at the top,
reproduce the problem, then send us:

- the message shown in the panel, and
- the log file:
  - Linux: `~/.kadas/agent_execution.log`
  - Windows: `C:\Users\<your name>\.kadas\agent_execution.log`

## Frequently asked questions

Is my map data sent to the AI company?

Your questions and information about your layers (names, coordinates) are sent to
Anthropic so it can answer. Your actual data files are not uploaded. If this is
unacceptable for your work, use [LOCAL_MODEL.md](LOCAL_MODEL.md) instead, where
nothing leaves your computer.

How much will it cost?

You pay Anthropic per question, typically a fraction of a cent each. Normal daily
use runs a few euros a month. Set a spend limit (Part 3, Step 2) to be certain.

Can several people share one key?

Technically yes, but it is better to give each person their own key. Then you can
see who used what and disable one key without affecting the others.

Does it work without internet?

Not with Claude. See [LOCAL_MODEL.md](LOCAL_MODEL.md) for the offline option.
