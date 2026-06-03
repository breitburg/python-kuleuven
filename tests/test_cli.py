import json

import pytest
import respx
from typer.testing import CliRunner

from kuleuven.cli import app
from kuleuven.toledo import (
    PORTAL_ENROLLMENTS_URL,
    ULTRA_API,
)


@pytest.fixture
def runner(monkeypatch, tmp_path) -> CliRunner:
    # Redirect cookie storage at the disk layer so the CLI's load/save
    # don't touch the user's real ~/.local/share/kuleuven path.
    monkeypatch.setattr(
        "kuleuven.cli.storage.cookies_path",
        lambda: tmp_path / "cookies.json",
    )
    return CliRunner()


def parse_stdout(result) -> dict:
    # Every CLI command emits exactly one JSON object on stdout (the contract
    # documented in CLAUDE.md). Decode and return it.
    return json.loads(result.stdout)


class TestCoursesList:
    def test_list_emits_one_json_object(self, runner, portal_course_payload):
        with respx.mock(assert_all_called=False) as mock:
            mock.get(PORTAL_ENROLLMENTS_URL).respond(json=[portal_course_payload])
            result = runner.invoke(app, ["toledo", "courses", "list"])

        assert result.exit_code == 0
        payload = parse_stdout(result)
        assert payload["status"] == "ok"
        assert payload["count"] == 1
        # Items are dumped from the Course model: snake_case fields.
        assert payload["items"][0]["batch_uid"] == "ULTRA-B-KUL-EX101a-2526"
        assert payload["items"][0]["course_code"] == "EX101a"

    def test_no_session_returns_error_json_on_stdout(self, runner):
        # 401 from the portal → CLI emits a `no_session` error JSON (still on
        # stdout, per the contract) and exits non-zero.
        with respx.mock(assert_all_called=False) as mock:
            mock.get(PORTAL_ENROLLMENTS_URL).respond(status_code=401)
            result = runner.invoke(app, ["toledo", "courses", "list"])

        assert result.exit_code == 1
        payload = parse_stdout(result)
        assert payload["status"] == "error"
        assert payload["code"] == "no_session"

    def test_filter_by_semester(self, runner, portal_course_payload):
        # Two courses, one in SEMESTER2 only. --semester filter trims the list.
        other = {**portal_course_payload, "id": "p2", "semester": "SEMESTER1"}
        with respx.mock(assert_all_called=False) as mock:
            mock.get(PORTAL_ENROLLMENTS_URL).respond(json=[portal_course_payload, other])
            result = runner.invoke(
                app, ["toledo", "courses", "list", "--semester", "SEMESTER2"]
            )

        payload = parse_stdout(result)
        assert payload["count"] == 1


class TestCoursesMembers:
    def test_members_command_emits_typed_membership_records(
        self, runner, portal_course_payload, ultra_membership_payload, membership_payload
    ):
        # The members command resolves the course via portal+ultra, then hits
        # /memberships and /memberships/counts.
        with respx.mock(assert_all_called=False) as mock:
            mock.get(PORTAL_ENROLLMENTS_URL).respond(json=[portal_course_payload])
            mock.get(f"{ULTRA_API}/users/me").respond(json={"id": "_me_1"})
            mock.get(f"{ULTRA_API}/users/_me_1/memberships").respond(
                json={"results": [ultra_membership_payload]}
            )
            mock.get(f"{ULTRA_API}/courses/_100001_1/memberships").respond(
                json={"results": [membership_payload]}
            )
            mock.get(f"{ULTRA_API}/courses/_100001_1/memberships/counts").respond(
                json={"results": {"STUDENT": 1}, "count": 1}
            )
            result = runner.invoke(app, ["toledo", "courses", "members", "EX101a"])

        payload = parse_stdout(result)
        assert payload["status"] == "ok"
        assert payload["count"] == 1
        assert payload["items"][0]["user"]["given_name"] == "Jane"
        # counts is the camelCase-keyed dict from MemberCounts.results
        assert payload["counts"] == {"STUDENT": 1}


class TestEmitContract:
    def test_emit_serializes_pydantic_models_via_default_hook(self):
        # The output module's _json_default falls back to model_dump for any
        # BaseModel — that's what lets CLI commands pass models straight into
        # the payload dict without manual conversion.
        from kuleuven.cli.output import _json_default
        from kuleuven.models import Course

        course = Course(batch_uid="X", display_name="Y")
        dumped = _json_default(course)
        assert dumped["batch_uid"] == "X"
        assert dumped["display_name"] == "Y"

    def test_emit_raises_typeerror_for_unsupported_types(self):
        from kuleuven.cli.output import _json_default

        with pytest.raises(TypeError, match="not JSON serializable"):
            _json_default(object())
