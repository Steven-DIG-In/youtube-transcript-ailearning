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
