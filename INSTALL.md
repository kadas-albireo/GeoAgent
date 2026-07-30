# KADAS GeoAgent: Installation Guide

GeoAgent adds an AI assistant panel to KADAS. You ask it to do things in plain
language, for example "load the aerial imagery", "draw a 500 m circle around
Bern", or "how far is it to Zurich?", and it operates the map for you.

This plugin works on both KADAS Albireo 2 and KADAS Albireo 3. It detects which
version you are running and adapts automatically. However the drawing annotations work differently from version 2 to 3, so the behavior of the agent will be different. Generally, it is recommended to run with 3. 

If you would rather not use an online AI service, or you need to work offline,
see [LOCAL_MODEL.md](LOCAL_MODEL.md). 

## Part 1: Install the plugin

The same file works on Windows and Linux.

### Step 1. Open KADAS

Start KADAS Albireo as you normally would.

### Installing

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
5. **Set the max token limit from auto to 30000**, or the maximum tokens you would like the agent to use per prompt. Note that this must be set if you are using Claude, otherwise there will be an out of tokens error.

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

## Part 3: Create an AI account and get your key

GeoAgent needs an account with an AI provider.

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

