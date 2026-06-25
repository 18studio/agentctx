import json
from types import SimpleNamespace

from agentctx import __version__, cli, paths


def write_auth(token):
    paths.codex_home().mkdir(parents=True, exist_ok=True)
    paths.codex_auth_path().write_text(json.dumps({"token": token}), encoding="utf-8")


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def setup_env(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTCTX_HOME", str(tmp_path / "agentctx"))
    monkeypatch.setenv("AGENTCTX_CODEX_HOME", str(tmp_path / "codex"))
    monkeypatch.setenv("AGENTCTX_IGNORE_FZF", "1")


def test_save_list_current_and_legacy_subcommands(tmp_path, monkeypatch, capsys):
    setup_env(tmp_path, monkeypatch)
    write_auth("work-token")

    assert cli.main(["work=."]) == 0
    assert paths.profile_auth_path("work").exists()
    assert cli.main(["--current"]) == 0
    assert capsys.readouterr().out.splitlines()[-1] == "work"
    assert cli.main(["-с"]) == 1  # Cyrillic small es, visually identical to -c
    captured = capsys.readouterr()
    assert 'error: unrecognized flag "-с"' in captured.err
    assert "USAGE:" in captured.out

    assert cli.main([]) == 0
    assert capsys.readouterr().out == "work\n"

    assert cli.main(["list"]) == 1
    captured = capsys.readouterr()
    assert "unsupported subcommand: list" in captured.err
    assert "work-token" not in captured.out + captured.err

    assert cli.main(["save", "work"]) == 1
    assert "unsupported subcommand: save" in capsys.readouterr().err


def test_switch_previous_and_auto_sync(tmp_path, monkeypatch, capsys):
    setup_env(tmp_path, monkeypatch)

    write_auth("work-v1")
    assert cli.main(["work=."]) == 0
    assert cli.main(["-u"]) == 0
    write_auth("personal-v1")
    assert cli.main(["personal=."]) == 0

    write_auth("personal-refreshed")
    assert cli.main(["work"]) == 0
    assert read_json(paths.codex_auth_path())["token"] == "work-v1"
    assert read_json(paths.profile_auth_path("personal"))["token"] == "personal-refreshed"
    assert paths.previous_file().read_text(encoding="utf-8").strip() == "personal"
    assert list(paths.backups_dir().glob("auth-*.json"))

    assert cli.main(["-"]) == 0
    assert read_json(paths.codex_auth_path())["token"] == "personal-refreshed"
    assert 'Switched to profile "personal".' in capsys.readouterr().out


def test_rename_current_dot_no_clobber_and_multi_delete(tmp_path, monkeypatch, capsys):
    setup_env(tmp_path, monkeypatch)

    write_auth("work")
    assert cli.main(["work=."]) == 0
    assert cli.main(["-u"]) == 0
    write_auth("old")
    assert cli.main(["old=."]) == 0
    assert cli.main(["work"]) == 0

    assert cli.main(["prod=."]) == 0
    assert not paths.profile_dir("work").exists()
    assert paths.profile_auth_path("prod").exists()
    assert paths.current_file().read_text(encoding="utf-8").strip() == "prod"

    assert cli.main(["old=prod"]) == 1
    assert paths.profile_auth_path("prod").exists()

    assert cli.main(["-d", "old", "prod"]) == 0
    assert not paths.profile_dir("old").exists()
    assert not paths.profile_dir("prod").exists()
    assert not paths.current_file().exists()
    assert not paths.previous_file().exists()
    captured = capsys.readouterr()
    assert 'Deleting profile "old"...' in captured.err


def test_long_aliases_and_version(tmp_path, monkeypatch, capsys):
    setup_env(tmp_path, monkeypatch)
    write_auth("work")
    assert cli.main(["work=."]) == 0
    assert cli.main(["--unset"]) == 0
    assert "Unsetting current profile." in capsys.readouterr().err
    assert cli.main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == "agentctx {0}".format(__version__)


def test_fzf_selector_switches_selected_profile(tmp_path, monkeypatch, capsys):
    setup_env(tmp_path, monkeypatch)
    monkeypatch.delenv("AGENTCTX_IGNORE_FZF", raising=False)
    write_auth("work")
    assert cli.main(["work=."]) == 0

    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(cli.sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/bin/fzf")
    monkeypatch.setattr(
        cli.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="work\n"),
    )

    assert cli.main([]) == 0
    assert 'Switched to profile "work".' in capsys.readouterr().out
