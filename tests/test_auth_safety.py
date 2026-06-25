import json
import os
import stat

from agentctx import cli, paths


def setup_env(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTCTX_HOME", str(tmp_path / "agentctx"))
    monkeypatch.setenv("AGENTCTX_CODEX_HOME", str(tmp_path / "codex"))
    monkeypatch.setenv("AGENTCTX_IGNORE_FZF", "1")
    paths.codex_home().mkdir(parents=True, exist_ok=True)


def mode(path):
    return stat.S_IMODE(path.stat().st_mode)


def test_invalid_json_is_rejected_without_secret_output(tmp_path, monkeypatch, capsys):
    setup_env(tmp_path, monkeypatch)
    paths.codex_auth_path().write_text('{"token": "SECRET",', encoding="utf-8")

    assert cli.main(["work=."]) == 1
    captured = capsys.readouterr()
    assert "invalid JSON" in captured.err
    assert "SECRET" not in captured.out + captured.err
    assert not paths.profile_dir("work").exists()


def test_symlink_active_auth_is_rejected(tmp_path, monkeypatch, capsys):
    setup_env(tmp_path, monkeypatch)
    target = tmp_path / "real-auth.json"
    target.write_text(json.dumps({"token": "SECRET"}), encoding="utf-8")
    os.symlink(str(target), str(paths.codex_auth_path()))

    assert cli.main(["work=."]) == 1
    captured = capsys.readouterr()
    assert "symlink" in captured.err
    assert "SECRET" not in captured.out + captured.err


def test_permissions_for_profile_active_and_backup_auth(tmp_path, monkeypatch):
    setup_env(tmp_path, monkeypatch)
    paths.codex_auth_path().write_text(json.dumps({"token": "work"}), encoding="utf-8")
    os.chmod(str(paths.codex_auth_path()), 0o644)
    assert cli.main(["work=."]) == 0
    assert mode(paths.codex_auth_path()) == 0o600
    assert mode(paths.profile_auth_path("work")) == 0o600

    assert cli.main(["-u"]) == 0
    paths.codex_auth_path().write_text(json.dumps({"token": "personal"}), encoding="utf-8")
    assert cli.main(["personal=."]) == 0
    assert cli.main(["work"]) == 0

    assert mode(paths.codex_auth_path()) == 0o600
    backups = list(paths.backups_dir().glob("auth-*.json"))
    assert backups
    assert all(mode(path) == 0o600 for path in backups)


def test_symlink_profile_auth_is_rejected_on_switch(tmp_path, monkeypatch, capsys):
    setup_env(tmp_path, monkeypatch)
    paths.codex_auth_path().write_text(json.dumps({"token": "work"}), encoding="utf-8")
    assert cli.main(["work=."]) == 0
    paths.profile_auth_path("work").unlink()
    target = tmp_path / "profile-auth.json"
    target.write_text(json.dumps({"token": "SECRET"}), encoding="utf-8")
    os.symlink(str(target), str(paths.profile_auth_path("work")))

    assert cli.main(["work"]) == 1
    captured = capsys.readouterr()
    assert "symlink" in captured.err
    assert "SECRET" not in captured.out + captured.err
