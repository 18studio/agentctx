"""Kubectx-like command-line interface for agentctx."""

import os
import shutil
import subprocess
import sys
from typing import Optional, Sequence

from agentctx import __version__, profiles
from agentctx.errors import AgentctxError

USAGE = """Manage and switch between Codex auth profiles.

USAGE:
  agentctx                       : list the profiles
  agentctx <NAME>                : switch to profile <NAME>
  agentctx -                     : switch to the previous profile
  agentctx -c, --current         : show the current profile name
  agentctx <NEW_NAME>=<NAME>     : rename profile <NAME> to <NEW_NAME>
  agentctx <NEW_NAME>=.          : save or rename current active auth to <NEW_NAME>
  agentctx -d <NAME> [<NAME...>] : delete profile <NAME> ('.' for current profile)
                                  (this command won't delete the active auth file
                                  that is used by Codex)
  agentctx -u, --unset           : unset the current profile

  agentctx -h,--help             : show this message
  agentctx -V,--version          : show version
"""


class UsageError(AgentctxError):
    """Error that should be followed by kubectx-style usage output."""


def _print_profile_list() -> int:
    output = profiles.format_profile_list(colored=sys.stdout.isatty() and not os.environ.get("NO_COLOR"))
    if output:
        print(output)
    return 0


def _maybe_interactive_select() -> Optional[str]:
    if not sys.stdout.isatty():
        return None
    if shutil.which("fzf") is None:
        return None

    if os.environ.get("AGENTCTX_IGNORE_FZF"):
        return None

    names = profiles.list_profiles()
    if not names:
        return None
    proc = subprocess.run(
        ["fzf"],
        input="\n".join(names) + "\n",
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()


def _list_or_select() -> int:
    selected = _maybe_interactive_select()
    if selected is None:
        return _print_profile_list()
    if not selected:
        print("error: you did not choose any of the options", file=sys.stderr)
        return 1
    profiles.switch_profile(selected)
    print('Switched to profile "{0}".'.format(selected))
    return 0


def _handle_rename_or_save(spec: str) -> int:
    new_name, old_name = spec.split("=", 1)
    if not new_name or not old_name:
        raise AgentctxError("invalid rename syntax: {0}".format(spec))
    if old_name == ".":
        outcome = profiles.save_or_rename_current(new_name)
        if outcome == "saved":
            print('Saved current Codex auth as profile "{0}".'.format(new_name))
        else:
            print('Current profile renamed to "{0}".'.format(new_name))
        return 0
    profiles.rename_profile(old_name, new_name)
    print('Profile "{0}" renamed to "{1}".'.format(old_name, new_name))
    return 0


def _reject_legacy_word(arg: str) -> None:
    if arg in profiles.LEGACY_WORDS:
        raise AgentctxError("unsupported subcommand: {0}".format(arg))


def run(argv: Sequence[str]) -> int:
    args = list(argv)

    if not args:
        return _list_or_select()

    if args in (["-h"], ["--help"]):
        print(USAGE, end="")
        return 0

    if args in (["-V"], ["--version"]):
        print("agentctx {0}".format(__version__))
        return 0

    if args in (["-c"], ["--current"]):
        print(profiles.current_profile_text())
        return 0

    if args in (["-u"], ["--unset"]):
        profiles.clear_current()
        print("Unsetting current profile.", file=sys.stderr)
        return 0

    if args[0] == "-d":
        if len(args) == 1:
            raise UsageError("error: missing profile NAME")
        deleted = profiles.delete_profiles(args[1:])
        for name in deleted:
            print('Deleting profile "{0}"...'.format(name), file=sys.stderr)
        return 0

    _reject_legacy_word(args[0])

    if len(args) != 1:
        raise UsageError("error: too many arguments")

    arg = args[0]

    if arg == "-":
        _, name = profiles.switch_previous()
        print('Switched to profile "{0}".'.format(name))
        return 0

    if "=" in arg:
        return _handle_rename_or_save(arg)

    if arg.startswith("-"):
        raise UsageError('error: unrecognized flag "{0}"'.format(arg))

    profiles.switch_profile(arg)
    print('Switched to profile "{0}".'.format(arg))
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    try:
        return run(sys.argv[1:] if argv is None else argv)
    except UsageError as exc:
        print(str(exc), file=sys.stderr)
        print(USAGE, end="")
        return 1
    except (AgentctxError, OSError, ValueError, FileNotFoundError) as exc:
        print("error: {0}".format(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
