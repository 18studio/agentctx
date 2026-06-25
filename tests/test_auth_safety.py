import base64
import json
import stat

from agentctx import cli, paths


def _b64url(value):
    return base64.urlsafe_b64encode(json.dumps(value).encode("utf-8")).decode("ascii").rstrip("=")


def make_jwt(email):
    return "{0}.{1}.".format(_b64url({"alg": "none", "typ": "JWT"}), _b64url({"email": email}))


def write_auth(label, email):
    auth_path = paths.codex_auth_path()
    if auth_path.exists() or auth_path.is_symlink():
        auth_path.unlink()
    auth_path.write_text(
        json.dumps({"tokens": {"id_token": make_jwt(email)}, "label": label}),
        encoding="utf-8",
    )


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

    assert cli.main(["=."]) == 1
    captured = capsys.readouterr()
    assert "invalid JSON" in captured.err
    assert "SECRET" not in captured.out + captured.err
    assert not paths.profile_dir("work@example.com").exists()


def test_missing_jwt_email_is_rejected_without_secret_output(tmp_path, monkeypatch, capsys):
    setup_env(tmp_path, monkeypatch)
    paths.codex_auth_path().write_text(json.dumps({"token": "SECRET"}), encoding="utf-8")

    assert cli.main(["=."]) == 1
    captured = capsys.readouterr()
    assert "JWT email not found" in captured.err
    assert "SECRET" not in captured.out + captured.err


def test_permissions_for_profile_active_and_backup_auth(tmp_path, monkeypatch):
    setup_env(tmp_path, monkeypatch)
    write_auth("work", "work@example.com")
    assert cli.main(["=."]) == 0
    assert paths.codex_auth_path().is_symlink()
    assert paths.profile_auth_path("work@example.com").is_symlink()
    assert mode(paths.codex_auth_path()) == 0o400
    assert mode(paths.profile_auth_path("work@example.com")) == 0o400

    assert cli.main(["-u"]) == 0
    write_auth("personal", "personal@example.com")
    assert cli.main(["=."]) == 0
    assert cli.main(["work@example.com"]) == 0

    assert paths.codex_auth_path().is_symlink()
    assert mode(paths.codex_auth_path()) == 0o400
    backups = list(paths.backups_dir().glob("auth-*.json"))
    assert backups
    assert all(mode(path) == 0o600 for path in backups)


def test_profile_jwt_files_are_not_overwritten_by_switch(tmp_path, monkeypatch):
    setup_env(tmp_path, monkeypatch)
    write_auth("work", "work@example.com")
    assert cli.main(["=."]) == 0
    work_target = paths.profile_auth_path("work@example.com").resolve()
    write_auth("personal", "personal@example.com")
    assert cli.main(["=."]) == 0

    assert cli.main(["work@example.com"]) == 0
    assert paths.codex_auth_path().resolve() == work_target
    assert json.loads(work_target.read_text(encoding="utf-8"))["label"] == "work"
