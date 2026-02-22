import os
import sys
import time
import subprocess
from datetime import datetime
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

class CommandRunner:
    def __init__(self, commands, files):
        self.commands = commands
        self.files = [os.path.abspath(f) for f in files]
        # Time when the most recent run started.
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

        print('\033[3J', end='')
        print('\033c', end='')
        if isinstance(self.commands, list):
            print(f"Running: {' '.join(self.commands)}")
        else:
            print(f"Running (shell): {self.commands}")
        print("▶"*3 + "-" * 7 + f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}" + "-" * 11)
        ok = False
        try:
            if isinstance(self.commands, list):
                subprocess.run(self.commands)
            else:
                subprocess.run(self.commands, shell=True)
            ok = True
        except Exception as e:
            print(f"Error running command: {e}")
        except KeyboardInterrupt:
            print("Canceled!")
        print(("✔" if ok else "✖")*3 + "-" * 7 + f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}" + "-" * 11)
        print("Watching for changes...")

class ChangeHandler(FileSystemEventHandler):
    def __init__(self, runner):
        self.runner = runner

    def on_modified(self, event):
        if event.is_directory:
            return

        file_path = os.path.abspath(event.src_path)
        if file_path in self.runner.files:
            self.runner.run(time.time())

    def on_created(self, event):
        if event.is_directory:
            return
        file_path = os.path.abspath(event.src_path)
        if file_path in self.runner.files:
            self.runner.run(time.time())


def print_help(prog_name: str) -> None:
    """Print command-line usage information."""
    usage = f"""Usage:
  {prog_name} [-g] <command> [files...]

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
    -g are treated as the command to execute on changes.
"""
    print(usage.rstrip())


def main(argv=None):
    """Simple file watcher that runs a command on change."""
    if argv is None:
        argv = sys.argv[1:]

    prog_name = os.path.basename(sys.argv[0] or "watcher")

    # No args or explicit help => show help
    if not argv or argv[0] in ("-h", "--help"):
        print_help(prog_name)
        return 0

    git = False
    shell = False

    # -g can only be the first flag
    if argv[0] == "-g":
        argv = argv[1:]
        if argv[0] == "-s":
            shell = True
            argv = argv[1:]
        git = True
        if not argv:
            print("Error: Git mode requires at least one argument for the command.", file=sys.stderr)
            return 1
    elif "-g" in argv[1:]:
        print("Error: -g must be the first argument if used.", file=sys.stderr)
        return 1
    if argv[0] == "-s":
        shell = True
        argv = argv[1:]

    if git:
        commands = argv
        try:
            files_output = subprocess.check_output(
                ["git", "ls-files"],
                text=True,
                stderr=subprocess.STDOUT,
            )
            files = files_output.strip().splitlines()
        except subprocess.CalledProcessError:
            print("Error: Not a git repository or git error while listing files.", file=sys.stderr)
            return 1
    else:
        commands = (argv[0] if shell else argv[0].split()) if argv else None
        file_args = argv[1:]

        if not commands:
            print("Error: Commands missing.", file=sys.stderr)
            return 1

        if not file_args:
            print("Error: At least one file must be specified to watch.", file=sys.stderr)
            return 1

        files = file_args

    # Filter out files that don't exist
    existing_files = [f for f in files if os.path.exists(f)]
    if not existing_files and not git:
        print(f"Error: None of the specified files exist: {', '.join(files)}", file=sys.stderr)
        return 1

    runner = CommandRunner(commands, existing_files)

    # Run once initially
    runner.run(time.time())

    event_handler = ChangeHandler(runner)
    observer = Observer()

    watched_dirs = set()
    for f in existing_files:
        dir_path = os.path.dirname(os.path.abspath(f))
        if os.path.exists(dir_path):
            watched_dirs.add(dir_path)

    if not watched_dirs:
        watched_dirs.add(".")

    for d in watched_dirs:
        observer.schedule(event_handler, d, recursive=True)

    observer.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


if __name__ == '__main__':
    sys.exit(main())
