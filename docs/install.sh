#!/bin/sh
# KU Leuven CLI installer for macOS and Linux.
#
#   curl -LsSf https://raw.githubusercontent.com/breitburg/python-kuleuven/main/docs/install.sh | sh
#
# Installs uv, installs the kuleuven CLI, signs in to your KU Leuven
# account, and optionally connects it to Claude Desktop.
set -eu

say() {
    printf '\n\033[1m%s\033[0m\n' "$1"
}

on_exit() {
    status=$?
    if [ "$status" -ne 0 ]; then
        printf '\n%s\n' "Something went wrong (exit code $status)."
        printf '%s\n' "Copy everything above and paste it into Claude (https://claude.ai)"
        printf '%s\n' "or any AI assistant, and ask what to do next."
    fi
}
trap on_exit EXIT

TTY=/dev/tty
if ! (: <"$TTY") 2>/dev/null || ! (: >"$TTY") 2>/dev/null; then
    echo "This installer needs an interactive terminal." >&2
    exit 1
fi

case "$(uname -s)" in
    Darwin | Linux) ;;
    *)
        echo "This installer supports macOS and Linux only." >&2
        echo "On Windows, follow the manual steps:" >&2
        echo "https://github.com/breitburg/python-kuleuven/blob/main/docs/index.md" >&2
        exit 1
        ;;
esac

export PATH="$HOME/.local/bin:$PATH"

if command -v uv >/dev/null 2>&1; then
    say "uv is already installed, good."
else
    say "Installing uv (the helper that manages everything else)..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
fi

say "Installing the kuleuven command (this can take a minute)..."
uv tool install --force git+https://github.com/breitburg/python-kuleuven
# Make sure future terminals find it too; harmless if already set up.
uv tool update-shell >/dev/null 2>&1 || true

if kuleuven session status >/dev/null 2>&1; then
    say "You are already signed in, skipping the sign-in."
else
    say "Sign in with your KU Leuven account."
    printf 'Username (like r0123456): ' >"$TTY"
    read -r KULEUVEN_USERNAME <"$TTY"
    printf 'Password (typing stays hidden): ' >"$TTY"
    stty -echo <"$TTY"
    read -r KULEUVEN_PASSWORD <"$TTY"
    stty echo <"$TTY"
    printf '\n' >"$TTY"
    export KULEUVEN_USERNAME KULEUVEN_PASSWORD

    say "Signing in... if your phone gets a KU Leuven notification, approve it."
    kuleuven session start <"$TTY"
fi

printf '\nConnect the KU Leuven tools to Claude Desktop? [Y/n] ' >"$TTY"
read -r connect_answer <"$TTY"
case "$connect_answer" in
    [nN]*)
        say "Skipped. Run 'kuleuven mcp install' later whenever you want to connect it."
        ;;
    *)
        kuleuven mcp install

        # Optionally store credentials in the Claude Desktop config so the
        # MCP server can refresh an expired session on its own (see README,
        # "Claude Desktop"). Opt-in only: it is a plain-text file on disk.
        if [ -n "${KULEUVEN_PASSWORD:-}" ]; then
            printf '\n%s\n' "Claude can sign in again by itself when your session expires (about" >"$TTY"
            printf '%s\n' "every two days) -- you would only approve a notification on your phone." >"$TTY"
            printf '%s\n' "For that, your username and password are stored in plain text in" >"$TTY"
            printf '%s\n' "Claude Desktop's config file on this computer." >"$TTY"
            printf 'Save them there? [y/N] ' >"$TTY"
            read -r save_answer <"$TTY"
            case "$save_answer" in
                [yY]*)
                    "$(uv tool dir)/python-kuleuven/bin/python" - <<'PYTHON'
import os

from claude_desktop_config.api import ClaudeDesktopConfig

cdc = ClaudeDesktopConfig()
config = cdc.read()
entry = config["mcpServers"]["kuleuven"]
env = entry.setdefault("env", {})
env["KULEUVEN_USERNAME"] = os.environ["KULEUVEN_USERNAME"]
env["KULEUVEN_PASSWORD"] = os.environ["KULEUVEN_PASSWORD"]
cdc.write(config)
print(f"Saved to {cdc.path}")
PYTHON
                    ;;
                *)
                    printf '%s\n' "Not saved. If Claude loses access later, run: kuleuven session start" >"$TTY"
                    ;;
            esac
        fi

        say "Done. Now quit Claude Desktop completely and open it again."
        printf '%s\n' "(On macOS: right-click its Dock icon and choose Quit. On the next start,"
        printf '%s\n' "ask Claude something like: 'List my Toledo courses.')"
        ;;
esac

say "All set."
