import os
import sys
import time
import subprocess
import click
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
        print(f"Running: {self.command}")
        print("-" * 40)
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

@click.command()
@click.argument('args', nargs=-1)
@click.option('-g', '--git', is_flag=True, help='Use git tracked files')
def main(args, git):
    """Simple file watcher that runs a command on change.
    
    If -g is not set:
    First arg is shell command, next args are files.
    
    If -g is set:
    All args are the shell command (concatenated), and it watches files from 'git ls-files'.
    """
    if not args and not git:
        click.echo("Error: No command or files provided.")
        sys.exit(1)

    if git:
        command = " ".join(args)
        try:
            files_output = subprocess.check_output(["git", "ls-files"], text=True)
            files = files_output.strip().splitlines()
        except subprocess.CalledProcessError:
            click.echo("Error: Not a git repository or git not found.")
            sys.exit(1)
    else:
        if len(args) < 1:
            click.echo("Error: Command missing.")
            sys.exit(1)
        command = args[0]
        files = args[1:]
        if not files:
            click.echo("Error: No files to watch specified.")
            sys.exit(1)

    runner = CommandRunner(command, files)
    
    # Run once initially
    runner.run()

    event_handler = ChangeHandler(runner)
    observer = Observer()
    
    # We watch directories that contain our files
    watched_dirs = set()
    for f in files:
        dir_path = os.path.dirname(os.path.abspath(f))
        if os.path.exists(dir_path):
            watched_dirs.add(dir_path)
        else:
            # File might not exist yet but we should still watch parent if it exists
            parent = os.path.dirname(dir_path)
            if os.path.exists(parent):
                watched_dirs.add(parent)

    if not watched_dirs:
        # Fallback to current directory
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
