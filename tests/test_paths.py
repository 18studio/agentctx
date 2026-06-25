from agentctx import paths


def test_env_overrides(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTCTX_HOME", str(tmp_path / "a"))
    monkeypatch.setenv("AGENTCTX_CODEX_HOME", str(tmp_path / "c"))

    assert paths.agentctx_home() == tmp_path / "a"
    assert paths.profiles_dir() == tmp_path / "a" / "profiles"
    assert paths.backups_dir() == tmp_path / "a" / "backups"
    assert paths.codex_auth_path() == tmp_path / "c" / "auth.json"
