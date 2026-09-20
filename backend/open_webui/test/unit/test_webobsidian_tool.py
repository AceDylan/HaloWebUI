"""The WebObsidian workspace tool (integrations/webobsidian-tool).

It is pasted into Workspace -> Tools rather than imported, so nothing in the app
exercises it. These tests load the file the way HaloWebUI does and hold the
three things that would be expensive to get wrong:

  - the tool surface offered to the model is exactly the four read-only calls
    (HaloWebUI turns *every* non-dunder attribute of the instance into a
    callable tool, so a helper named `_get` would become one);
  - a path coming from the model can never walk out of the vault or into
    `.git` / `.trash`, and is refused here rather than sent;
  - every request carries a bounded timeout and the X-API-Key header, and an
    unconfigured tool says so instead of raising.
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

TOOL_PATH = (
    Path(__file__).resolve().parents[4]
    / "integrations"
    / "webobsidian-tool"
    / "webobsidian_tool.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("webobsidian_tool_under_test", TOOL_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


module = _load_module()


def _tool(**valves):
    tool = module.Tools()
    tool.valves = tool.Valves(
        **{"base_url": "https://notes.example:3003", "api_key": "wok_test_key", **valves}
    )
    return tool


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text_body=None):
        self.status_code = status_code
        self._payload = payload
        self._text = text_body

    def json(self):
        if self._text is not None:
            raise ValueError("not json")
        return self._payload


class Recorder:
    """Stands in for requests.get and remembers every call."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, params=None, headers=None, timeout=None, verify=None):
        self.calls.append(
            {"url": url, "params": params or {}, "headers": headers or {}, "timeout": timeout,
             "verify": verify}
        )
        return self.responses.pop(0) if self.responses else FakeResponse(200, {})


@pytest.fixture
def patched(monkeypatch):
    def install(*responses):
        recorder = Recorder(*responses)
        monkeypatch.setattr(module.requests, "get", recorder)
        return recorder

    return install


# -- the surface offered to the model ------------------------------------


def test_the_model_is_offered_exactly_the_four_read_only_calls():
    import inspect

    tool = module.Tools()
    offered = {
        name
        for name in dir(tool)
        if callable(getattr(tool, name))
        and not name.startswith("__")
        and not inspect.isclass(getattr(tool, name))
    }
    assert offered == {"search_notes", "read_note", "list_notes", "find_backlinks"}


def test_every_offered_call_documents_itself_for_the_model():
    tool = module.Tools()
    for name in ("search_notes", "read_note", "list_notes", "find_backlinks"):
        doc = getattr(tool, name).__doc__ or ""
        assert ":param" in doc and ":return:" in doc, name


def test_the_default_valves_are_empty_so_a_fresh_install_reaches_nothing():
    valves = module.Tools().Valves()
    assert valves.base_url == "" and valves.api_key == ""
    assert valves.verify_tls is True


# -- path handling -------------------------------------------------------


@pytest.mark.parametrize(
    "hostile",
    [
        "../../etc/passwd",
        "Notes/../../etc/passwd",
        "..\\..\\windows\\system32",
        ".git/config",
        "Notes/.git/config",
        ".trash/Deleted.md",
        ".obsidian/workspace.json",
        "Notes//Ideas.md",
        "Notes/\x00Ideas.md",
        "Notes/Ideas\n.md",
        "a" * 500,
        "",
        None,
    ],
)
def test_a_path_that_could_leave_the_vault_is_refused_before_any_request(hostile, patched):
    recorder = patched()
    tool = _tool()
    assert "not a valid vault path" in tool.read_note(hostile)
    assert "not a valid vault path" in tool.find_backlinks(hostile)
    assert recorder.calls == []


def test_a_leading_slash_is_stripped_the_way_the_agent_api_does_it():
    # The model sometimes writes "/Notes/Ideas.md". WebObsidian drops the leading
    # slash itself and resolves the rest inside the vault, so mirror that here
    # rather than refusing a path that would have worked.
    assert module._clean_path("/Notes/Ideas.md") == "Notes/Ideas.md"
    assert module._clean_path("/etc/passwd") == "etc/passwd"
    assert module._clean_path("//etc/passwd") == "etc/passwd"


def test_an_ordinary_path_survives_cleaning():
    for good in ("Welcome.md", "Notes/Ideas.md", "项目/2026/计划.md", "a b/c d.md"):
        assert module._clean_path(good) == good
    assert module._clean_path("/Notes/Ideas.md") == "Notes/Ideas.md"
    assert module._clean_path("  Notes/Ideas.md  ") == "Notes/Ideas.md"


def test_a_note_link_percent_encodes_every_segment():
    tool = _tool()
    assert module._note_url(tool.valves, "项目/a b.md") == (
        "https://notes.example:3003/note/%E9%A1%B9%E7%9B%AE/a%20b.md"
    )
    # Characters that would otherwise start a query or a fragment are encoded.
    assert module._note_url(tool.valves, "a?b#c.md").endswith("/note/a%3Fb%23c.md")
    assert module._note_url(_tool(base_url="").valves, "a.md") == ""


# -- requests ------------------------------------------------------------


def test_a_search_sends_the_key_as_a_header_with_a_bounded_timeout(patched):
    recorder = patched(
        FakeResponse(200, {"hits": [{"path": "Notes/Ideas.md", "title": "Ideas",
                                     "snippet": "a  b\n c", "tags": ["idea"]}]})
    )
    answer = _tool().search_notes("graph", limit=3)

    call = recorder.calls[0]
    assert call["url"] == "https://notes.example:3003/api/v1/search"
    assert call["headers"]["X-API-Key"] == "wok_test_key"
    assert "Authorization" not in call["headers"]
    assert 1.0 <= call["timeout"] <= 30.0
    assert call["params"] == {"q": "graph", "limit": 3}
    assert "Notes/Ideas.md" in answer
    assert "a b c" in answer  # whitespace in the snippet is collapsed
    assert "https://notes.example:3003/note/Notes/Ideas.md" in answer


@pytest.mark.parametrize(
    "asked,expected", [(1, 1), (5, 5), (999, 10), (-3, 1), ("4", 4), (None, 5), ("nope", 5)]
)
def test_the_model_cannot_ask_for_more_hits_than_the_valve_allows(asked, expected, patched):
    recorder = patched(FakeResponse(200, {"hits": []}))
    _tool().search_notes("graph", limit=asked)
    assert recorder.calls[0]["params"]["limit"] == expected


def test_a_silly_timeout_valve_is_clamped_into_range():
    assert module._timeout(_tool(timeout_seconds=0.001).valves) == 1.0
    assert module._timeout(_tool(timeout_seconds=9999).valves) == 30.0
    assert module._timeout(_tool().valves) == 8.0


def test_a_long_note_is_truncated_and_says_so(patched):
    patched(FakeResponse(200, {"content": "x" * 20000, "title": "Big", "tags": []}))
    answer = json.loads(_tool(max_note_chars=600).read_note("Notes/Big.md"))
    assert answer["truncated"] is True
    assert answer["content"] == "x" * 600


def test_a_short_note_is_not_marked_truncated(patched):
    patched(FakeResponse(200, {"content": "hello", "title": "Hi", "tags": ["a"]}))
    answer = json.loads(_tool().read_note("Notes/Hi.md"))
    assert answer["truncated"] is False and answer["content"] == "hello"


def test_listing_filters_by_folder_and_reports_the_top_level_folders(patched):
    patched(
        FakeResponse(
            200,
            {"notes": ["Welcome.md", "项目/a.md", "项目/b.md", "知识库/c.md", "../escape.md"]},
        )
    )
    answer = _tool().list_notes(folder="项目")
    assert "项目/a.md" in answer and "项目/b.md" in answer
    assert "知识库/c.md" not in answer and "escape" not in answer

    patched(FakeResponse(200, {"notes": ["Welcome.md", "项目/a.md", "知识库/c.md"]}))
    everything = _tool().list_notes()
    assert '"total": 3' in everything and "知识库" in everything


def test_backlinks_are_deduplicated_and_cleaned(patched):
    patched(FakeResponse(200, {"backlinks": ["b.md", "a.md", "a.md", "../nope.md", ""]}))
    answer = _tool().find_backlinks("Notes/Ideas.md")
    assert answer.index('"a.md"') < answer.index('"b.md"')
    assert answer.count('"a.md"') == 1
    assert "nope" not in answer


def test_nothing_linking_back_reads_as_a_sentence(patched):
    patched(FakeResponse(200, {"backlinks": []}))
    assert "Nothing links to" in _tool().find_backlinks("Notes/Ideas.md")


# -- failure modes -------------------------------------------------------


def test_an_unconfigured_tool_explains_itself_instead_of_calling_out(patched):
    recorder = patched()
    assert "not configured" in _tool(base_url="").search_notes("x")
    assert "not configured" in _tool(api_key="").search_notes("x")
    assert recorder.calls == []


def test_an_empty_query_never_reaches_the_vault(patched):
    recorder = patched()
    assert "Give me something" in _tool().search_notes("   ")
    assert recorder.calls == []


@pytest.mark.parametrize(
    "status,expected",
    [
        (401, "refused the API key"),
        (403, "missing a scope"),
        (404, "Not found in the vault"),
        (429, "rate-limiting"),
        (500, "HTTP 500"),
    ],
)
def test_every_http_failure_becomes_a_sentence_the_model_can_relay(status, expected, patched):
    patched(FakeResponse(status, {}))
    assert expected in _tool().search_notes("graph")


def test_a_timeout_or_a_dead_host_is_reported_not_raised(monkeypatch):
    def timeout(*_args, **_kwargs):
        raise module.requests.Timeout()

    monkeypatch.setattr(module.requests, "get", timeout)
    assert "did not answer within" in _tool().search_notes("graph")

    def refused(*_args, **_kwargs):
        raise module.requests.ConnectionError()

    monkeypatch.setattr(module.requests, "get", refused)
    assert "Could not reach WebObsidian" in _tool().search_notes("graph")


def test_a_non_json_answer_is_reported(patched):
    patched(FakeResponse(200, text_body="<html>nope</html>"))
    assert "not JSON" in _tool().search_notes("graph")


def test_a_search_with_no_usable_hit_says_so_rather_than_inventing_one(patched):
    patched(FakeResponse(200, {"hits": [{"path": "../escape.md"}, "junk", {}]}))
    assert "No note in the vault matches" in _tool().search_notes("graph")
