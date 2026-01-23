import os
import sys
import time
import subprocess
import click
from datetime import datetime
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

class CommandRunner:
    def __init__(self, command, files):
        self.command = command
        self.files = [os.path.abspath(f) for f in files]
        self.last_run_time = 0
        self.debounce_interval = 0.5  # Prevent rapid multiple runs

    def run(self):
        now = time.time()
        if now - self.last_run_time < self.debounce_interval:
            return
        
        self.last_run_time = now
        click.clear()
        print('\033[3J', end='')
        print('\033c', end='')
        print(f"Running: {self.command}")
        print("-" * 10 + f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}" + "-" * 11)
        try:
            subprocess.run(self.command, shell=True)
        except Exception as e:
            print(f"Error running command: {e}")
        print("-" * 40)
        print("Watching for changes...")

class ChangeHandler(FileSystemEventHandler):
    def __init__(self, runner):
        self.runner = runner

    def on_modified(self, event):
        if event.is_directory:
            return
        
        file_path = os.path.abspath(event.src_path)
        if file_path in self.runner.files:
            self.runner.run()

    def on_created(self, event):
        if event.is_directory:
            return
        file_path = os.path.abspath(event.src_path)
        if file_path in self.runner.files:
            self.runner.run()

@click.command(no_args_is_help=True, context_settings={"help_option_names": ["-h", "--help"]})
@click.argument('command', nargs=1)
@click.argument('args', nargs=-1)
@click.option('-g', '--git', is_flag=True, help='Use git tracked files. If set, all args are treated as the command.')
def main(command, args, git):
    """Simple file watcher that runs a command on change.
    """
    if git:
        if not command:
            raise click.UsageError("Git mode requires at least one argument for the command.")
        command = (command + " " + " ".join(args)).strip()
        try:
            files_output = subprocess.check_output(["git", "ls-files"], text=True, stderr=subprocess.STDOUT)
            files = files_output.strip().splitlines()
        except subprocess.CalledProcessError:
            raise click.ClickException("Not a git repository or git error while listing files.")
    else:
        if not command:
             raise click.UsageError("Command missing.")
        if not args:
             raise click.UsageError("At least one file must be specified to watch.")
        
        files = args

    # Filter out files that don't exist
    existing_files = [f for f in files if os.path.exists(f)]
    if not existing_files and not git:
        raise click.ClickException(f"None of the specified files exist: {', '.join(files)}")
    
    runner = CommandRunner(command, existing_files)
    
    # Run once initially
    runner.run()

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
    main()
