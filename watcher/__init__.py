import os
import sys
import time
import subprocess
from datetime import datetime
from watchdog.observers import Observer
from watchdog.observers.polling import PollingObserver
from watchdog.events import FileSystemEventHandler

def main(argv=None):
    """Simple file watcher that runs a command on change."""
    if argv is None: argv = sys.argv[1:]
    prog_name = os.path.basename(sys.argv[0] or "watcher")

    if not argv or argv[0] in ("-h", "--help"):
        print_help(prog_name)
        return 0

    try:
        args = parse_args(list(argv))
    except ArgError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    commands = args["command"]
    files = args["files"]

    # Filter out files that don't exist
    for f in list(files):
        if not os.path.exists(f):
            print(f"Warning: File not found: {f}", file=sys.stderr)
            files.remove(f)
    if not files:
        print(f"Error: None of the specified files exist: {', '.join(files)}", file=sys.stderr)
        return 1

    runner = CommandRunner(commands)
    runner.run(time.time())  # Run once initially
    event_handler = ChangeHandler(runner)
    observer = PollingObserver()

    for f in files:
        if os.path.isdir(f):
            observer.schedule(event_handler, f, recursive=True)
        else:
            observer.schedule(event_handler, f, recursive=False)

    observer.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
    return 0


class CommandRunner:
    def __init__(self, commands):
        self.commands = commands
        self.last_run_start_time = 0.0

    def run(self, request_time: float):
        """Request a run at the given request_time.

        Any request whose timestamp is not strictly newer than the last
        run start time is ignored.
        """
        # Ignore stale requests that are not newer than the last run start.
        if request_time <= self.last_run_start_time:
            return

        # Record when this run starts; any later request_time will trigger
        # another run, earlier ones will be ignored.
        self.last_run_start_time = request_time

        # Clear screen (scroll buffer + reset)
        print('\033[3J\033c', end='')
        if isinstance(self.commands, list):
            print(f"Running: {' '.join(self.commands)}")
        else:
            print(f"Running (shell): {self.commands}")
        print("▶" * 3 + "-" * 7 + f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}" + "-" * 11)

        ok = False
        try:
            if isinstance(self.commands, list):
                result = subprocess.run(self.commands)
            else:
                result = subprocess.run(self.commands, shell=True)
            ok = result.returncode == 0
        except FileNotFoundError as e:
            print(f"Error: command not found: {e}")
        except OSError as e:
            print(f"Error running command: {e}")
        except KeyboardInterrupt:
            print("Canceled!")

        print(("✔" if ok else "✖") * 3 + "-" * 7 + f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}" + "-" * 11)
        print("Watching for changes...")


class ChangeHandler(FileSystemEventHandler):
    def __init__(self, runner):
        self.runner = runner

    def _handle(self, event):
        print("HALLOU!")
        self.runner.run(time.time())

    def on_modified(self, event):
        self._handle(event)

    def on_created(self, event):
        self._handle(event)


def print_help(prog_name: str) -> None:
    """Print command-line usage information."""
    usage = f"""Usage:
  {prog_name} [-g] [-s] <command> [files...]

Options:
  -s          Treat command as a shell command
  -g          Use git tracked files. All remaining arguments are treated
              as the command to run.
  -h, --help  Show this help message and exit.

Behavior:
  Without -g:
    The first argument is the command to run, and the remaining arguments
    are the files to watch for changes.

  With -g:
    All tracked files from `git ls-files` are watched. All arguments after
    flags are treated as the command to execute on changes.
"""
    print(usage.rstrip())


class ArgError(Exception):
    """Raised by parse_args on invalid input. Message is user-facing."""


FLAGS = {"-g", "-s", "-h", "--help"}


def parse_args(argv: list[str]) -> dict:
    """Parse and validate CLI arguments.

    Returns a dict with keys:
        command  - list[str] (argv-style) or str (shell string)
        files    - list[str] of paths to watch  (empty list in git mode
                   before filtering; populated from git ls-files)
        shell    - bool, whether to pass command to the shell
        git      - bool, whether files come from git ls-files

    Raises ArgError with a descriptive message on any validation failure.
    Raises SystemExit(1) only when git ls-files itself fails.
    """
    if not argv:
        raise ArgError("No arguments provided. Run with -h for usage.")

    argv = list(argv)  # don't mutate the caller's list
    git = False
    shell = False

    # --- flag: -g (must be first if present) ---
    if argv[0] == "-g":
        git = True
        argv.pop(0)
    elif "-g" in argv:
        raise ArgError("-g must be the first argument if used.")

    # --- flag: -s (optional, must come before command) ---
    if argv and argv[0] == "-s":
        shell = True
        argv.pop(0)

    # --- unknown flags still in argv ---
    flags_in_argv = [a for a in argv if a in FLAGS]
    if flags_in_argv:
        print(f"Warning: Unexpected flag(s) after command position: {', '.join(flags_in_argv)}")

    # --- command ---
    if not argv or not (raw_command := argv[0].strip()):
        raise ArgError("No command specified after flags.")

    if shell:
        command: list | str = raw_command          # kept as a shell string
    else:
        command = raw_command.split()              # split on whitespace

    # --- files ---
    if git:
        try:
            out = subprocess.check_output(
                ["git", "ls-files"],
                text=True,
                stderr=subprocess.STDOUT,
            )
            files = out.strip().splitlines()
        except subprocess.CalledProcessError as exc:
            print(f"Error: git ls-files failed (exit {exc.returncode}).", file=sys.stderr)
            sys.exit(1)

        if not files:
            raise ArgError("git ls-files returned no files — is the repository empty?")
    else:
        files = argv[1:]
        if not files:
            raise ArgError("At least one file to watch must be specified after the command.")

        # Warn about arguments that look like flags passed after the command.
        flag_like = [f for f in files if f in FLAGS]
        if flag_like:
            raise ArgError(
                f"Unexpected flag(s) in file list: {', '.join(flag_like)}. "
                "Flags must appear before the command."
            )

    # Resolve all file paths to absolute so that CommandRunner.files,
    # watched_dirs, and ChangeHandler._handle all agree regardless of CWD.
    files = [os.path.abspath(f) for f in files]

    return {"command": command, "files": files, "shell": shell, "git": git}





if __name__ == '__main__':
    sys.exit(main())
