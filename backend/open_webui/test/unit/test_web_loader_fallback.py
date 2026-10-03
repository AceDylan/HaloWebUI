from open_webui.retrieval import runtime
from open_webui.retrieval.web import utils


def test_firecrawl_loader_without_the_package_downloads_pages_itself(monkeypatch):
    monkeypatch.setattr(utils, "_firecrawl_package_available", lambda: False)

    loader = utils.get_web_loader(["https://example.com/a"], loader_engine="firecrawl")

    assert isinstance(loader, utils.SafeWebBaseLoader)


def test_firecrawl_is_reported_unavailable_without_the_package(monkeypatch):
    monkeypatch.setattr(
        runtime, "_module_available", lambda name: name != "firecrawl"
    )

    assert runtime.get_runtime_capabilities()["firecrawl_available"] is False
