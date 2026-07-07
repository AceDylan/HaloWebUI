from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def read_repo_file(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_hermes_agent_provider_is_registered_for_user_connections_and_models():
    user_connections = read_repo_file("open_webui/utils/user_connections.py")
    models = read_repo_file("open_webui/utils/models.py")
    chat = read_repo_file("open_webui/utils/chat.py")
    main = read_repo_file("open_webui/main.py")

    assert '"hermes"' in user_connections
    assert '"HERMES_AGENT_BASE_URLS"' in user_connections
    assert 'hermes_agent.get_all_models' in models
    assert 'generate_hermes_agent_chat_completion' in chat
    assert 'prefix="/hermes-agent"' in main


def test_hermes_agent_router_exposes_config_models_and_proxy_endpoints():
    router = read_repo_file("open_webui/routers/hermes_agent.py")

    assert '@router.get("/config")' in router
    assert '@router.post("/config/update")' in router
    assert '@router.get("/models")' in router
    assert '@router.post("/v1/chat/completions")' in router
    assert '@router.post("/v1/responses")' in router
    assert 'Authorization' in router
    assert 'Bearer' in router


def test_frontend_connections_page_exposes_hermes_agent_settings():
    connections = read_repo_file("../src/lib/components/admin/Settings/Connections.svelte")
    api = read_repo_file("../src/lib/apis/hermes-agent/index.ts")

    assert "getHermesAgentConfig" in connections
    assert "updateHermesAgentConfig" in connections
    assert "HERMES_AGENT_BASE_URLS" in connections
    assert "http://127.0.0.1:8642/v1" in connections
    assert "HaloWebUI proxies the API key server-side" in connections
    assert "HERMES_AGENT_API_BASE_URL" in api
