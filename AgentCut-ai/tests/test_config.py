"""Verify credential-file isolation without opening the real .env file."""

import builtins
import io
import os
from pathlib import Path
import runpy

import pytest


CONFIG = Path(__file__).resolve().parents[1] / "app" / "config.py"


@pytest.mark.parametrize("load_dotenv", ["false", "0", "off", "true", None])
def test_dotenv_loading_can_be_disabled(monkeypatch, load_dotenv):
    if load_dotenv is None:
        monkeypatch.delenv("AGENTCUT_LOAD_DOTENV", raising=False)
    else:
        monkeypatch.setenv("AGENTCUT_LOAD_DOTENV", load_dotenv)
    monkeypatch.setenv("AGENTCUT_AI_SIMULATE", "true")
    monkeypatch.setenv("AGENTCUT_VLM_API_KEY", "")
    monkeypatch.setenv("AGENTCUT_LLM_API_KEY", "")
    monkeypatch.setenv("AGENTCUT_TEST_ENV_MARKER", "shell")
    opened = []
    original_open = builtins.open
    original_exists = os.path.exists

    def fake_open(path, *args, **kwargs):
        if str(path).endswith(".env"):
            opened.append(path)
            return io.StringIO("AGENTCUT_TEST_ENV_MARKER=file\n")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", fake_open)
    monkeypatch.setattr(os.path, "exists", lambda path: True if str(path).endswith(".env") else original_exists(path))
    config = runpy.run_path(str(CONFIG))

    assert bool(opened) == (load_dotenv in ("true", None))
    assert os.environ["AGENTCUT_TEST_ENV_MARKER"] == "shell"
    assert config["SIMULATE_FORCED"] is True
    assert config["VLM_API_KEY"] == config["LLM_API_KEY"] == ""
