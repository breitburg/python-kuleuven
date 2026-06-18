import click
import typer
from typer.cli import get_docs_for_click

from kuleuven.cli.output import emit


def docs() -> None:
    """Print Markdown docs for every command and subcommand as JSON."""
    # Imported lazily: kuleuven.cli builds `app` by importing this module.
    from kuleuven.cli import app

    # get_docs_for_click is Typer's own recursive Markdown generator (the one
    # behind `typer utils docs`). It renders usage, arguments, and options
    # through the same code path as `--help`, so the output never drifts from
    # the real CLI. A throwaway context is enough; the callback that builds the
    # session never runs because we aren't executing a command.
    root = typer.main.get_command(app)
    context = click.Context(root, info_name="kuleuven")
    markdown = get_docs_for_click(obj=root, ctx=context, name="kuleuven")
    emit({"status": "ok", "format": "markdown", "docs": markdown.strip()})
