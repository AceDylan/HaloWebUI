"""Load the plugin as a package (its directory name has a hyphen) against a throwaway Kanban.

Run with Hermes' venv (the plugin imports hermes_cli.kanban_db):
  cd integrations/hermes-plugin/halowebui-teams
  /usr/local/lib/hermes-agent/venv/bin/python -m pytest tests -q -p no:cacheprovider
"""

import importlib.util
import os
import sys
import tempfile
from pathlib import Path

import pytest

_TMP = tempfile.mkdtemp(prefix="halo-teams-test-")
os.environ["HERMES_KANBAN_HOME"] = _TMP
os.environ["HERMES_HOME"] = os.path.join(_TMP, "home")
os.environ["HERMES_HALO_TEAMS_NO_NUDGE"] = "1"
os.environ["HALO_TEAMS_BRIDGE"] = "0"
os.environ["HALO_TEAMS_WORKSPACE_ROOT"] = os.path.join(_TMP, "workspaces")
os.environ["HALO_TEAMS_RUNS_HOME"] = _TMP  # <runner>-runs for every runner member kind
os.environ["HALO_TEAMS_RECLAUDE_RUNS_ROOT"] = os.path.join(_TMP, "reclaude-runs")
os.environ["HALO_TEAMS_TASK_DIR"] = os.path.join(_TMP, "tasks")
os.environ["HALO_TEAMS_RUNNERS_FILE"] = os.path.join(_TMP, "halo-teams-runners.json")
os.environ["HALO_TEAMS_CONCLUSION_SYNC"] = "1"
os.environ["HALO_TEAMS_LEAD_SYNC"] = "1"
for key in [k for k in os.environ if k.startswith("HERMES_KANBAN_") and k != "HERMES_KANBAN_HOME"]:
    del os.environ[key]
os.makedirs(os.environ["HERMES_HOME"], exist_ok=True)
sys.path.insert(0, "/usr/local/lib/hermes-agent")

_PLUGIN_DIR = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location(
    "halowebui_teams", _PLUGIN_DIR / "__init__.py", submodule_search_locations=[str(_PLUGIN_DIR)]
)
plugin = importlib.util.module_from_spec(_SPEC)
sys.modules["halowebui_teams"] = plugin
_SPEC.loader.exec_module(plugin)


class FakeAvailability:
    """Every runner available unless a test marks it down: tests never probe real runners."""

    def __init__(self):
        self.down = {}
        self.calls = 0

    def __call__(self, names=None, *, force=False):
        import halowebui_teams.runners as runners

        self.calls += 1
        out = {}
        for name in names or runners.NAMES:
            reason = self.down.get(name)
            out[name] = {"name": name, "label": name, "available": reason is None,
                         "state": "ok" if reason is None else "unreachable", "reason": reason or "可用",
                         "checked_at": 0, "layers": []}
        return out


@pytest.fixture(autouse=True)
def availability(monkeypatch):
    import halowebui_teams.runners as runners

    fake = FakeAvailability()
    monkeypatch.setattr(runners, "check", fake)
    return fake


@pytest.fixture
def pkg():
    import halowebui_teams.common as common
    import halowebui_teams.hooks as hooks
    import halowebui_teams.plan as plan
    import halowebui_teams.reclaude as reclaude
    import halowebui_teams.teams as teams
    import halowebui_teams.runners as runners
    import halowebui_teams.fallback as fallback
    import halowebui_teams.assistants as assistants
    import halowebui_teams.conclusion as conclusion

    return type("Pkg", (), {"common": common, "hooks": hooks, "plan": plan, "teams": teams, "reclaude": reclaude,
                            "runners": runners, "fallback": fallback, "assistants": assistants,
                            "conclusion": conclusion})


PLAN = {
    "title": "小工具开发",
    "summary": "后端和前端并行，最后评审",
    "members": [
        {"name": "backend-dev", "role": "后端开发", "executor": "hermes", "focus": "接口"},
        {"name": "frontend-dev", "role": "前端开发", "executor": "hermes", "focus": "页面"},
        {"name": "reviewer", "role": "评审", "executor": "hermes", "focus": "检查"},
    ],
    "tasks": [
        {"key": "T1", "title": "写接口", "description": "写 api.md", "member": "backend-dev", "depends_on": []},
        {"key": "T2", "title": "写页面", "description": "写 page.md", "member": "frontend-dev", "depends_on": []},
        {"key": "T3", "title": "评审", "description": "检查 api.md 和 page.md", "member": "reviewer",
         "depends_on": ["T1", "T2"]},
    ],
}


@pytest.fixture
def plan_dict():
    import copy

    return copy.deepcopy(PLAN)


@pytest.fixture
def team_id():
    import uuid

    return str(uuid.uuid4())
