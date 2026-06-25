import base64
import json
from types import SimpleNamespace

from agentctx import __version__, cli, paths


def _b64url(value):
    return base64.urlsafe_b64encode(json.dumps(value).encode("utf-8")).decode("ascii").rstrip("=")


def make_jwt(email):
    return "{0}.{1}.".format(_b64url({"alg": "none", "typ": "JWT"}), _b64url({"email": email}))


def write_auth(label, email):
    paths.codex_home().mkdir(parents=True, exist_ok=True)
    auth_path = paths.codex_auth_path()
    if auth_path.exists() or auth_path.is_symlink():
        auth_path.unlink()
    auth_path.write_text(
        json.dumps({"tokens": {"id_token": make_jwt(email)}, "label": label}),
        encoding="utf-8",
    )


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def setup_env(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTCTX_HOME", str(tmp_path / "agentctx"))
    monkeypatch.setenv("AGENTCTX_CODEX_HOME", str(tmp_path / "codex"))
    monkeypatch.setenv("AGENTCTX_IGNORE_FZF", "1")


def test_save_list_current_and_legacy_subcommands(tmp_path, monkeypatch, capsys):
    setup_env(tmp_path, monkeypatch)
    write_auth("work-token", "work@example.com")

    assert cli.main(["=."]) == 0
    assert paths.profile_auth_path("work@example.com").exists()
    assert cli.main(["--current"]) == 0
    assert capsys.readouterr().out.splitlines()[-1] == "work@example.com"
    assert cli.main(["-с"]) == 1  # Cyrillic small es, visually identical to -c
    captured = capsys.readouterr()
    assert 'error: unrecognized flag "-с"' in captured.err
    assert "USAGE:" in captured.out

    assert cli.main([]) == 0
    assert capsys.readouterr().out == "work@example.com\n"

    assert cli.main(["list"]) == 1
    captured = capsys.readouterr()
    assert "unsupported subcommand: list" in captured.err
    assert "work-token" not in captured.out + captured.err

    assert cli.main(["save", "work@example.com"]) == 1
    assert "unsupported subcommand: save" in capsys.readouterr().err


def test_save_dot_validates_explicit_name_matches_jwt_email(tmp_path, monkeypatch, capsys):
    setup_env(tmp_path, monkeypatch)
    write_auth("work-token", "work@example.com")

    assert cli.main(["other@example.com=."]) == 1
    captured = capsys.readouterr()
    assert "profile name must match JWT email: work@example.com" in captured.err
    assert not paths.profile_dir("work@example.com").exists()

    assert cli.main(["work@example.com=."]) == 0
    assert paths.profile_auth_path("work@example.com").exists()


def test_login_runs_codex_browser_login_and_saves_jwt_email_profile(tmp_path, monkeypatch, capsys):
    setup_env(tmp_path, monkeypatch)
    write_auth("work-token", "work@example.com")
    calls = []

    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/bin/codex" if name == "codex" else None)
    def fake_codex_login(cmd, **kwargs):
        calls.append(cmd)
        write_auth("work-token", "work@example.com")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(cli.subprocess, "run", fake_codex_login)

    assert cli.main(["login"]) == 0
    assert calls == [["/usr/bin/codex", "login"]]
    assert paths.profile_auth_path("work@example.com").exists()
    assert paths.current_file().read_text(encoding="utf-8").strip() == "work@example.com"
    assert 'Logged in and saved Codex auth as profile "work@example.com".' in capsys.readouterr().out


def test_login_creates_new_profile_without_renaming_previous_current(tmp_path, monkeypatch, capsys):
    setup_env(tmp_path, monkeypatch)
    write_auth("old-token", "old@example.com")
    assert cli.main(["=."]) == 0
    calls = []

    def fake_codex_login(cmd, **kwargs):
        calls.append(cmd)
        write_auth("new-token", "new@example.com")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/bin/codex" if name == "codex" else None)
    monkeypatch.setattr(cli.subprocess, "run", fake_codex_login)

    assert cli.main(["login"]) == 0
    assert calls == [["/usr/bin/codex", "login"]]
    assert paths.profile_auth_path("old@example.com").exists()
    assert paths.profile_auth_path("new@example.com").exists()
    assert read_json(paths.profile_auth_path("old@example.com"))["label"] == "old-token"
    assert read_json(paths.profile_auth_path("new@example.com"))["label"] == "new-token"
    assert paths.current_file().read_text(encoding="utf-8").strip() == "new@example.com"
    assert paths.previous_file().read_text(encoding="utf-8").strip() == "old@example.com"
    assert 'Logged in and saved Codex auth as profile "new@example.com".' in capsys.readouterr().out


def test_login_rejects_arguments(tmp_path, monkeypatch, capsys):
    setup_env(tmp_path, monkeypatch)

    assert cli.main(["login", "expected@example.com"]) == 1
    assert "login does not accept arguments" in capsys.readouterr().err


def test_login_reports_missing_codex(tmp_path, monkeypatch, capsys):
    setup_env(tmp_path, monkeypatch)
    monkeypatch.setattr(cli.shutil, "which", lambda name: None)

    assert cli.main(["login"]) == 1
    assert "codex executable not found in PATH" in capsys.readouterr().err


def test_switch_previous_uses_symlink_without_auto_sync(tmp_path, monkeypatch, capsys):
    setup_env(tmp_path, monkeypatch)

    write_auth("work-v1", "work@example.com")
    assert cli.main(["=."]) == 0
    assert cli.main(["-u"]) == 0
    write_auth("personal-v1", "personal@example.com")
    assert cli.main(["=."]) == 0

    write_auth("personal-refreshed", "personal@example.com")
    assert cli.main(["work@example.com"]) == 0
    assert paths.codex_auth_path().is_symlink()
    assert read_json(paths.codex_auth_path())["label"] == "work-v1"
    assert read_json(paths.profile_auth_path("personal@example.com"))["label"] == "personal-v1"
    assert paths.previous_file().read_text(encoding="utf-8").strip() == "personal@example.com"
    assert list(paths.backups_dir().glob("auth-*.json"))

    assert cli.main(["-"]) == 0
    assert read_json(paths.codex_auth_path())["label"] == "personal-v1"
    assert 'Switched to profile "personal@example.com".' in capsys.readouterr().out


def test_switch_does_not_sync_foreign_jwt_into_current_email_profile(tmp_path, monkeypatch):
    setup_env(tmp_path, monkeypatch)

    write_auth("old-v1", "old@example.com")
    assert cli.main(["=."]) == 0
    assert cli.main(["-u"]) == 0
    write_auth("new-v1", "new@example.com")
    assert cli.main(["=."]) == 0
    assert cli.main(["old@example.com"]) == 0

    write_auth("foreign-active", "new@example.com")
    assert cli.main(["new@example.com"]) == 0

    assert read_json(paths.profile_auth_path("old@example.com"))["label"] == "old-v1"
    assert read_json(paths.profile_auth_path("new@example.com"))["label"] == "new-v1"


def test_delete_email_profiles(tmp_path, monkeypatch, capsys):
    setup_env(tmp_path, monkeypatch)

    write_auth("work", "work@example.com")
    assert cli.main(["=."]) == 0
    assert cli.main(["-u"]) == 0
    write_auth("old", "old@example.com")
    assert cli.main(["=."]) == 0
    assert cli.main(["work@example.com"]) == 0

    assert cli.main(["-d", "old@example.com", "work@example.com"]) == 0
    assert not paths.profile_dir("old@example.com").exists()
    assert not paths.profile_dir("work@example.com").exists()
    assert not paths.current_file().exists()
    assert not paths.previous_file().exists()
    captured = capsys.readouterr()
    assert 'Deleting profile "old@example.com"...' in captured.err


def test_long_aliases_and_version(tmp_path, monkeypatch, capsys):
    setup_env(tmp_path, monkeypatch)
    write_auth("work", "work@example.com")
    assert cli.main(["=."]) == 0
    assert cli.main(["--unset"]) == 0
    assert "Unsetting current profile." in capsys.readouterr().err
    assert cli.main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == "agentctx {0}".format(__version__)


def test_fzf_selector_switches_selected_profile(tmp_path, monkeypatch, capsys):
    setup_env(tmp_path, monkeypatch)
    monkeypatch.delenv("AGENTCTX_IGNORE_FZF", raising=False)
    write_auth("work", "work@example.com")
    assert cli.main(["=."]) == 0

    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(cli.sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/bin/fzf")
    monkeypatch.setattr(
        cli.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="work@example.com\n"),
    )

    assert cli.main([]) == 0
    assert 'Switched to profile "work@example.com".' in capsys.readouterr().out
