import re

from open_webui.utils.middleware import (
    _citation_context,
    _citation_index_map,
    _sources_for_ui,
)


def web_source(query, url, text):
    # Shape chat_web_search_handler + get_sources_from_files produce with
    # BYPASS_WEB_SEARCH_EMBEDDING_AND_RETRIEVAL: one page per source, no file_id.
    return {
        "source": {"name": query, "type": "web_search", "urls": [url]},
        "document": [text],
        "metadata": [{"source": url, "title": url.rsplit("/", 1)[-1]}],
    }


def context_ids(context):
    return [
        (int(number), text)
        for number, text in re.findall(r'<source id="(\d+)">(.*?)</source>', context)
    ]


def test_each_web_page_gets_its_own_number_in_ui_order():
    sources = [
        web_source("q1", "https://a.example/1", "A"),
        web_source("q1", "https://b.example/2", "B"),
        web_source("q2", "https://c.example/3", "C"),
        # The same page found by a second query keeps its first number.
        web_source("q2", "https://a.example/1", "A again"),
    ]
    sources_for_ui = _sources_for_ui(sources, [])

    assert [s["metadata"][0]["source"] for s in sources_for_ui] == [
        "https://a.example/1",
        "https://b.example/2",
        "https://c.example/3",
    ]
    assert context_ids(_citation_context(sources, sources_for_ui)) == [
        (1, "A"),
        (2, "B"),
        (3, "C"),
        (1, "A again"),
    ]


def test_chunks_of_one_file_share_a_number_and_files_differ():
    sources = [
        {
            "source": {"id": "file-a", "name": "a.pdf"},
            "document": ["a1", "a2"],
            "metadata": [
                {"file_id": "file-a", "name": "a.pdf", "source": "a.pdf"},
                {"file_id": "file-a", "name": "a.pdf", "source": "a.pdf"},
            ],
        },
        {
            # Full-context files carry no metadata source; the file id numbers them.
            "source": {"id": "file-b", "name": "b.txt"},
            "document": ["b"],
            "metadata": [{"file_id": "file-b", "name": "b.txt"}],
        },
    ]
    sources_for_ui = _sources_for_ui(sources, [])

    assert _citation_index_map(sources_for_ui) == {"a.pdf": 1, "file-b": 2}
    assert context_ids(_citation_context(sources, sources_for_ui)) == [
        (1, "a1"),
        (1, "a2"),
        (2, "b"),
    ]


def test_sources_the_ui_does_not_show_are_numbered_after_the_shown_ones():
    unnamed = {
        "source": {"id": "hidden"},
        "document": ["hidden text"],
        "metadata": [{"source": "https://hidden.example/"}],
    }
    shown = web_source("q", "https://shown.example/", "shown text")
    tool_source = {
        "source": {"id": "https://tool.example/", "name": "Tool page"},
        "document": ["tool text"],
        "metadata": [{"source": "web:https://tool.example/"}],
    }
    sources_for_ui = _sources_for_ui([unnamed, shown], [tool_source])

    assert sources_for_ui == [shown, tool_source]
    # [1] in the answer must open the first source the UI lists.
    assert context_ids(_citation_context([unnamed, shown], sources_for_ui)) == [
        (3, "hidden text"),
        (1, "shown text"),
    ]
