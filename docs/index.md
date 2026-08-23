# Getting started with Claude Desktop

This guide connects your KU Leuven account to Claude, the AI assistant. Once set up, you can ask Claude things like "what's new in my courses?" or "book me a study seat in the library tomorrow morning", and it will do it for you.

No prior knowledge is needed. You will type a few commands into a terminal, which is a window where you give your computer text instructions. The whole setup takes about 10 minutes, and you only do it once.

## What you will install

- **uv** — a small helper program that installs and runs the KU Leuven tool for you. It also takes care of Python, the language the tool is written in, so you don't need to install anything else yourself.
- **The `kuleuven` tool** — the program that talks to Toledo and KURT with your account.
- **Claude Desktop** — the Claude app for your computer, if you don't have it yet.

## Step 1: Open a terminal

- **macOS**: press `Cmd + Space`, type `Terminal`, press Enter.
- **Windows**: press the Windows key, type `PowerShell`, press Enter.

A window appears where you can type commands. For each step below, copy the command, paste it into this window, and press Enter.

## Step 2: Install uv

**macOS:**

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Windows:**

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

When it finishes, close the terminal window and open a new one (step 1 again) so the computer picks up the new program.

## Step 3: Install the KU Leuven tool

```sh
uv tool install git+https://github.com/breitburg/python-kuleuven
```

This downloads the tool and everything it needs. It can take a minute. To check it worked, run:

```sh
kuleuven --help
```

If you see a list of commands, you're good. If you see "command not found", close the terminal and open a new one, then try again.

## Step 4: Sign in to your KU Leuven account

```sh
kuleuven session start
```

It asks for your KU Leuven username (like `r0123456`) and password. When you type the password, nothing appears on screen. That is normal, just type it and press Enter.

Then confirm the sign-in the same way you do for Toledo: approve the notification on your phone, or enter the code from your authenticator app.

When it prints a message containing `"status": "ok"`, you are signed in. Your password is not saved anywhere; only the session is, and it lasts about two days.

## Step 5: Install Claude Desktop

If you don't have it yet, download it from [claude.ai/download](https://claude.ai/download) and sign in with a Claude account. If you already have it, skip ahead.

## Step 6: Connect the tool to Claude

```sh
kuleuven mcp install
```

Then quit Claude Desktop completely and open it again. On macOS, right-click its Dock icon and choose Quit; on Windows, also quit it from the system tray near the clock, since closing the window alone is not enough.

## Step 7: Try it

Open Claude Desktop and ask something like:

> List my Toledo courses.

or:

> Which study seats are free in the library tomorrow between 9 and 12?

The first time, Claude will ask for permission to use the KU Leuven tools. Allow it, and you're done.

## When it stops working

Your session expires after about two days. If Claude says it can't reach your courses anymore, open a terminal and sign in again:

```sh
kuleuven session start
```

No restart of Claude Desktop needed after that.

## Removing everything

To disconnect the tool from Claude Desktop:

```sh
kuleuven mcp uninstall
```

To sign out and delete the saved session:

```sh
kuleuven session end
```

To remove the tool itself:

```sh
uv tool uninstall python-kuleuven
```
