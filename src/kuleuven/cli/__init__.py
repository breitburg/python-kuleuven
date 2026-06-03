import httpx
import typer
from dotenv import load_dotenv

from kuleuven.cli import storage
from kuleuven.cli.content import content_app
from kuleuven.cli.courses import courses_app
from kuleuven.cli.discussions import discussions_app
from kuleuven.cli.files import files_app
from kuleuven.cli.kurt import kurt_app
from kuleuven.cli.mcp import mcp_app
from kuleuven.cli.raw import raw
from kuleuven.cli.session import session_app
from kuleuven.session import USER_AGENT, KuleuvenSession

load_dotenv()

app = typer.Typer(no_args_is_help=True, help="KU Leuven CLI")


@app.callback()
def main(ctx: typer.Context) -> None:
    http_client = httpx.Client(
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
        timeout=30.0,
    )
    storage.load_cookies(http_client)
    ctx.obj = KuleuvenSession(http_client=http_client)
    ctx.call_on_close(ctx.obj.close)


# Everything Toledo is course-scoped, so content/files/discussions nest
# under `courses` instead of sitting as peer subgroups. The `toledo`
# wrapper stays as a service namespace alongside `kurt` and any future
# KU Leuven services.
courses_app.add_typer(content_app, name="content")
courses_app.add_typer(files_app, name="files")
courses_app.add_typer(discussions_app, name="discussions")

toledo_app = typer.Typer(
    no_args_is_help=True,
    help="Toledo portal and Blackboard Ultra",
)
toledo_app.add_typer(courses_app, name="courses")

session_app.command(name="raw")(raw)

app.add_typer(session_app, name="session")
app.add_typer(toledo_app, name="toledo")
app.add_typer(kurt_app, name="kurt")
app.add_typer(mcp_app, name="mcp")
