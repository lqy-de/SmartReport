"""Exercise the Windows script against disposable local bare remotes only."""

import os
from pathlib import Path
import shutil
import subprocess

import pytest


pytestmark = pytest.mark.skipif(os.name != "nt" or not shutil.which("git"),
                                reason="Requires Windows CMD and Git")
SCRIPT = Path(__file__).resolve().parents[1] / "sync_repos.bat"


def git(cwd, *arguments):
    result = subprocess.run(["git", *arguments], cwd=cwd, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=30)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def commit(cwd, message):
    git(cwd, "add", ".")
    git(cwd, "-c", "user.name=Synthetic Tester", "-c", "user.email=test@example.invalid",
        "-c", "commit.gpgsign=false", "commit", "-m", message)
    return git(cwd, "rev-parse", "HEAD")


@pytest.fixture
def repositories(tmp_path):
    work = tmp_path / "中文 source with spaces"
    work.mkdir()
    git(work, "init", "-b", "main")
    shutil.copyfile(SCRIPT, work / "sync_repos.bat")
    (work / "source.txt").write_text("synthetic initial state\n", encoding="utf-8")
    commit(work, "test: synthetic initial state")
    remotes = {}
    for name in ("github", "gitee"):
        destination = tmp_path / f"{name}.git"
        git(tmp_path, "init", "--bare", str(destination))
        git(work, "remote", "add", name, str(destination))
        remotes[name] = destination
    return work, remotes


def sync(work):
    return subprocess.run(["cmd.exe", "/d", "/c", "sync_repos.bat"], cwd=work,
                          capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=45)


def test_sync_success_verifies_both_heads_and_preserves_history(repositories):
    work, remotes = repositories
    # Slashes in branch names must work too.
    git(work, "switch", "-c", "feature/synthetic")
    result = sync(work)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "[GitHub] SUCCESS" in result.stdout and "[Gitee] SUCCESS" in result.stdout
    expected = git(work, "rev-parse", "HEAD")
    for remote in remotes.values():
        assert git(work, "--git-dir", str(remote), "rev-parse", "refs/heads/feature/synthetic") == expected
    (work / "source.txt").write_text("synthetic update\n", encoding="utf-8")
    newer = commit(work, "test: synthetic update")
    assert sync(work).returncode == 0
    for remote in remotes.values():
        assert git(work, "--git-dir", str(remote), "rev-parse", "refs/heads/feature/synthetic") == newer
        assert git(work, "--git-dir", str(remote), "rev-parse", f"{newer}^") == expected


@pytest.mark.parametrize("change", ["untracked", "modified", "staged"])
def test_sync_stops_before_any_push_for_uncommitted_files(repositories, change):
    work, remotes = repositories
    target = work / ("new.txt" if change == "untracked" else "source.txt")
    target.write_text("not committed\n", encoding="utf-8")
    if change == "staged":
        git(work, "add", "source.txt")
    result = sync(work)
    assert result.returncode != 0
    assert "Uncommitted or untracked changes found" in result.stdout
    for remote in remotes.values():
        assert git(work, "--git-dir", str(remote), "for-each-ref") == ""


def test_sync_reports_partial_failure_without_overwriting_remote(repositories, tmp_path):
    work, remotes = repositories
    assert sync(work).returncode == 0
    other = tmp_path / "other"
    git(tmp_path, "clone", "--branch", "main", str(remotes["gitee"]), str(other))
    (other / "remote-only.txt").write_text("remote change\n", encoding="utf-8")
    remote_head = commit(other, "test: remote divergence")
    git(other, "push", "origin", "main")
    (work / "local-only.txt").write_text("local change\n", encoding="utf-8")
    local_head = commit(work, "test: local divergence")
    result = sync(work)
    assert result.returncode != 0
    assert "[GitHub] SUCCESS" in result.stdout and "[Gitee] FAILED" in result.stdout
    assert "[SUCCESS] Both repositories" not in result.stdout
    assert git(work, "--git-dir", str(remotes["github"]), "rev-parse", "main") == local_head
    assert git(work, "--git-dir", str(remotes["gitee"]), "rev-parse", "main") == remote_head


@pytest.mark.parametrize("problem", ["missing", "same-url", "multiple-urls", "detached"])
def test_sync_rejects_unsafe_setup_without_push(repositories, problem):
    work, remotes = repositories
    if problem == "missing":
        git(work, "remote", "remove", "gitee")
    elif problem == "same-url":
        git(work, "remote", "set-url", "gitee", str(remotes["github"]))
    elif problem == "multiple-urls":
        git(work, "config", "--add", "remote.github.pushurl", str(remotes["github"]))
        git(work, "config", "--add", "remote.github.pushurl", str(remotes["gitee"]))
    else:
        git(work, "checkout", "--detach")
    assert sync(work).returncode != 0
    for remote in remotes.values():
        assert git(work, "--git-dir", str(remote), "for-each-ref") == ""
