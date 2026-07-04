import subprocess

from vault_push import push_vault


def _git(cwd, *a):
    subprocess.run(["git", "-C", cwd, *a], check=True, capture_output=True)


def _seeded_repo(tmp_path):
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    repo = tmp_path / "wiki"
    repo.mkdir()
    _git(str(repo), "init")
    _git(str(repo), "config", "user.email", "t@t")
    _git(str(repo), "config", "user.name", "t")
    (repo / "vaults/AI Learnings").mkdir(parents=True)
    (repo / "vaults/AI Learnings/seed.md").write_text("seed")
    _git(str(repo), "add", ".")
    _git(str(repo), "commit", "-m", "seed")
    _git(str(repo), "remote", "add", "origin", str(remote))
    _git(str(repo), "push", "-u", "origin", "HEAD")
    return repo


def test_push_vault_commits_only_subpath(tmp_path):
    repo = _seeded_repo(tmp_path)
    (repo / "vaults/Other").mkdir(parents=True)
    (repo / "vaults/AI Learnings/new.md").write_text("new note")
    (repo / "vaults/Other/x.md").write_text("unrelated dirt")  # must NOT be committed

    assert push_vault(str(repo)) is True
    log = subprocess.run(["git", "-C", str(repo), "show", "--stat", "HEAD"],
                         capture_output=True, text=True).stdout
    assert "new.md" in log and "x.md" not in log


def test_push_vault_nothing_to_push_is_true(tmp_path):
    repo = _seeded_repo(tmp_path)
    head_before = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                                 capture_output=True, text=True).stdout
    assert push_vault(str(repo)) is True
    head_after = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                                capture_output=True, text=True).stdout
    assert head_before == head_after  # no empty commit created


def test_push_vault_failure_returns_false(tmp_path):
    repo = _seeded_repo(tmp_path)
    _git(str(repo), "remote", "set-url", "origin", str(tmp_path / "gone.git"))  # unreachable
    (repo / "vaults/AI Learnings/new.md").write_text("new")
    assert push_vault(str(repo)) is False  # returns, never raises


def test_push_vault_ignores_prestaged_files_outside_subpath(tmp_path):
    """A pathspec-scoped commit must not sweep in files someone else staged."""
    repo = _seeded_repo(tmp_path)
    (repo / "vaults/Other").mkdir(parents=True)
    (repo / "vaults/Other/x.md").write_text("pre-staged dirt")
    _git(str(repo), "add", "vaults/Other/x.md")  # staged BEFORE push_vault runs
    (repo / "vaults/AI Learnings/new.md").write_text("new note")

    assert push_vault(str(repo)) is True
    log = subprocess.run(["git", "-C", str(repo), "show", "--stat", "HEAD"],
                         capture_output=True, text=True).stdout
    assert "new.md" in log and "x.md" not in log
    # The out-of-subpath file must remain staged and uncommitted.
    staged = subprocess.run(["git", "-C", str(repo), "diff", "--cached", "--name-only"],
                            capture_output=True, text=True).stdout
    assert "vaults/Other/x.md" in staged


def test_push_vault_recovers_unpushed_commit_after_failed_push(tmp_path):
    """Commit-succeeded-push-failed must not strand the commit: the next run
    (clean porcelain but ahead of upstream) must push it and return True."""
    repo = _seeded_repo(tmp_path)
    remote = tmp_path / "remote.git"
    _git(str(repo), "remote", "set-url", "origin", str(tmp_path / "gone.git"))
    (repo / "vaults/AI Learnings/new.md").write_text("new")
    assert push_vault(str(repo)) is False  # commit lands locally, push fails

    _git(str(repo), "remote", "set-url", "origin", str(remote))  # network restored
    assert push_vault(str(repo)) is True  # NO new file changes — must still push
    local_head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                                capture_output=True, text=True).stdout.strip()
    remote_head = subprocess.run(["git", "-C", str(remote), "rev-parse", "HEAD"],
                                 capture_output=True, text=True).stdout.strip()
    assert local_head == remote_head  # the stranded commit reached the remote
