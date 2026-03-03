"""Tests for watcher.py"""
import os
import sys
import time
import types
import pytest
from unittest.mock import MagicMock, patch, call

import watcher as W
from watcher import CommandRunner, ChangeHandler, ArgError, parse_args, main


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_event(path, is_directory=False):
    """Create a minimal mock FileSystemEvent."""
    event = MagicMock()
    event.src_path = path
    event.is_directory = is_directory
    return event


# ---------------------------------------------------------------------------
# CommandRunner
# ---------------------------------------------------------------------------

class TestCommandRunner:
    def test_stale_request_is_ignored(self):
        runner = CommandRunner(["echo", "hi"], [])
        runner.last_run_start_time = 100.0
        with patch("subprocess.run") as mock_run:
            runner.run(50.0)   # older than last_run_start_time
            mock_run.assert_not_called()

    def test_equal_timestamp_is_ignored(self):
        runner = CommandRunner(["echo", "hi"], [])
        runner.last_run_start_time = 100.0
        with patch("subprocess.run") as mock_run:
            runner.run(100.0)
            mock_run.assert_not_called()

    def test_fresh_request_runs(self):
        runner = CommandRunner(["echo", "hi"], [])
        runner.last_run_start_time = 0.0
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            runner.run(1.0)
            mock_run.assert_called_once_with(["echo", "hi"])

    def test_last_run_start_time_updated(self):
        runner = CommandRunner(["echo", "hi"], [])
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            runner.run(42.0)
            assert runner.last_run_start_time == 42.0

    def test_shell_command_string(self):
        runner = CommandRunner("echo hello", [])
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            runner.run(1.0)
            mock_run.assert_called_once_with("echo hello", shell=True)

    def test_nonzero_exit_prints_failure_marker(self, capsys):
        runner = CommandRunner(["false"], [])
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1)
            runner.run(1.0)
        out = capsys.readouterr().out
        assert "✖" in out

    def test_zero_exit_prints_success_marker(self, capsys):
        runner = CommandRunner(["true"], [])
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            runner.run(1.0)
        out = capsys.readouterr().out
        assert "✔" in out

    def test_file_not_found_prints_error(self, capsys):
        runner = CommandRunner(["no_such_command_xyz"], [])
        with patch("subprocess.run", side_effect=FileNotFoundError("no_such_command_xyz")):
            runner.run(1.0)
        out = capsys.readouterr().out
        assert "Error" in out

    def test_files_stored_as_absolute_paths(self, tmp_path):
        f = tmp_path / "a.txt"
        runner = CommandRunner(["echo"], [str(f)])
        assert os.path.abspath(str(f)) in runner.files

    def test_files_is_a_set(self, tmp_path):
        f = tmp_path / "a.txt"
        runner = CommandRunner(["echo"], [str(f)])
        assert isinstance(runner.files, set)

    def test_sequential_runs_both_execute(self):
        runner = CommandRunner(["echo"], [])
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            runner.run(1.0)
            runner.run(2.0)
            assert mock_run.call_count == 2


# ---------------------------------------------------------------------------
# ChangeHandler
# ---------------------------------------------------------------------------

class TestChangeHandler:
    def setup_method(self):
        self.runner = MagicMock()
        self.handler = ChangeHandler(self.runner)

    def _set_files(self, paths):
        self.runner.files = {os.path.abspath(p) for p in paths}

    def test_on_modified_known_file_triggers_run(self, tmp_path):
        f = tmp_path / "watched.py"
        self._set_files([str(f)])
        event = _make_event(str(f))
        self.handler.on_modified(event)
        self.runner.run.assert_called_once()

    def test_on_created_known_file_triggers_run(self, tmp_path):
        f = tmp_path / "watched.py"
        self._set_files([str(f)])
        event = _make_event(str(f))
        self.handler.on_created(event)
        self.runner.run.assert_called_once()

    def test_unknown_file_does_not_trigger_run(self, tmp_path):
        self._set_files([str(tmp_path / "watched.py")])
        event = _make_event(str(tmp_path / "other.py"))
        self.handler.on_modified(event)
        self.runner.run.assert_not_called()

    def test_directory_event_is_ignored(self, tmp_path):
        f = tmp_path / "watched.py"
        self._set_files([str(f)])
        event = _make_event(str(f), is_directory=True)
        self.handler.on_modified(event)
        self.runner.run.assert_not_called()

    def test_run_called_with_current_time(self, tmp_path):
        f = tmp_path / "watched.py"
        self._set_files([str(f)])
        before = time.time()
        event = _make_event(str(f))
        self.handler.on_modified(event)
        after = time.time()
        call_arg = self.runner.run.call_args[0][0]
        assert before <= call_arg <= after


# ---------------------------------------------------------------------------
# parse_args
# ---------------------------------------------------------------------------

class TestParseArgs:
    def test_simple_command_and_files(self):
        r = parse_args(["echo", "file1.py", "file2.py"])
        assert r["command"] == ["echo"]
        assert r["files"] == ["file1.py", "file2.py"]
        assert r["shell"] is False
        assert r["git"] is False

    def test_multiword_command_split(self):
        r = parse_args(["echo hello", "file.py"])
        assert r["command"] == ["echo", "hello"]

    def test_shell_flag_keeps_command_as_string(self):
        r = parse_args(["-s", "echo hello world", "file.py"])
        assert r["command"] == "echo hello world"
        assert r["shell"] is True

    def test_returns_dict_with_all_keys(self):
        r = parse_args(["echo", "file.py"])
        assert set(r.keys()) == {"command", "files", "shell", "git"}

    def test_no_args_raises_argerror(self):
        with pytest.raises(W.ArgError, match="No arguments"):
            parse_args([])

    def test_no_files_raises_argerror(self):
        with pytest.raises(W.ArgError, match="file"):
            parse_args(["echo"])

    def test_no_command_after_shell_flag_raises(self):
        with pytest.raises(W.ArgError):
            parse_args(["-s"])

    def test_g_midstream_raises_argerror(self):
        with pytest.raises(W.ArgError, match="-g must be the first"):
            parse_args(["echo", "-g", "file.py"])

    def test_git_no_command_raises_argerror(self):
        with pytest.raises(W.ArgError, match="command"):
            with patch("subprocess.check_output", return_value="a.py\n"):
                parse_args(["-g"])

    def test_empty_command_string_raises(self):
        with pytest.raises(W.ArgError, match="No command specified"):
            parse_args(["", "file.py"])

    def test_whitespace_only_command_raises(self):
        with pytest.raises(W.ArgError, match="No command specified"):
            parse_args(["   ", "file.py"])

    def test_flag_in_file_list_raises(self):
        with pytest.raises(W.ArgError, match="Unexpected flag"):
            parse_args(["echo", "file.py", "-s"])

    def test_git_mode_command_list(self):
        with patch("subprocess.check_output", return_value="a.py\nb.py\n"):
            r = parse_args(["-g", "pytest"])
        assert r["command"] == ["pytest"]
        assert "a.py" in r["files"] and "b.py" in r["files"]
        assert r["git"] is True

    def test_git_mode_shell(self):
        with patch("subprocess.check_output", return_value="a.py\n"):
            r = parse_args(["-g", "-s", "make test"])
        assert r["command"] == "make test"
        assert r["shell"] is True

    def test_git_mode_empty_repo_raises(self):
        with patch("subprocess.check_output", return_value="\n"):
            with pytest.raises(W.ArgError, match="empty"):
                parse_args(["-g", "pytest"])

    def test_git_mode_ls_files_failure_exits(self):
        import subprocess as sp
        with patch("subprocess.check_output", side_effect=sp.CalledProcessError(128, "git")):
            with pytest.raises(SystemExit):
                parse_args(["-g", "pytest"])

    def test_does_not_mutate_input(self):
        original = ["echo", "file.py"]
        copy = list(original)
        parse_args(original)
        assert original == copy


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------

class TestMain:
    def _run(self, args):
        """Run main() with mocked observer and runner."""
        with patch("watcher.Observer") as MockObserver, \
             patch("watcher.CommandRunner") as MockRunner, \
             patch("watcher.ChangeHandler"):
            mock_obs = MockObserver.return_value
            mock_runner = MockRunner.return_value
            # Raise KeyboardInterrupt to exit the watch loop immediately
            mock_obs.start.side_effect = KeyboardInterrupt
            result = main(args)
        return result, MockRunner, mock_obs

    def test_no_args_prints_help(self, capsys):
        ret = main([])
        assert ret == 0
        assert "Usage" in capsys.readouterr().out

    def test_help_flag(self, capsys):
        ret = main(["-h"])
        assert ret == 0
        assert "Usage" in capsys.readouterr().out

    def test_help_long_flag(self, capsys):
        ret = main(["--help"])
        assert ret == 0
        assert "Usage" in capsys.readouterr().out

    def test_missing_file_warns(self, capsys):
        with patch("watcher.Observer") as MockObserver, \
             patch("watcher.CommandRunner"), \
             patch("watcher.ChangeHandler"), \
             patch("watcher.time") as mock_time:
            mock_time.sleep.side_effect = KeyboardInterrupt
            mock_time.time.return_value = 1.0
            main(["echo", "/nonexistent_file_xyz_abc.py"])
        err = capsys.readouterr().err
        assert "Warning" in err

    def test_returns_zero_on_clean_exit(self, tmp_path):
        f = tmp_path / "a.py"
        f.write_text("x")
        with patch("watcher.Observer"), \
             patch("watcher.CommandRunner"), \
             patch("watcher.ChangeHandler"), \
             patch("watcher.time") as mock_time:
            mock_time.sleep.side_effect = KeyboardInterrupt
            mock_time.time.return_value = 1.0
            ret = main(["echo", str(f)])
        assert ret == 0
