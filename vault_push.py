"""Commit+push the AI Learnings vault after each ingest run — fixes the
uncommitted-vault gotcha at the source (spec §3a). Never raises."""
import subprocess
import sys

WIKI_ROOT = "/Users/steven/Vibe Projects/wiki-knowledge-interface"
SUBPATH = "vaults/AI Learnings"


def push_vault(wiki_root: str = WIKI_ROOT, subpath: str = SUBPATH) -> bool:
    def git(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", "-C", wiki_root, *args],
                              capture_output=True, text=True, timeout=120)
    try:
        status = git("status", "--porcelain", "--", subpath)
        if status.returncode != 0:
            sys.stderr.write(f"[vault_push] status failed: {status.stderr}\n"); return False
        if not status.stdout.strip():
            return True  # nothing to push
        if git("add", "--", subpath).returncode != 0:
            return False
        commit = git("commit", "-m", "yt-ingest: vault update (auto)")
        if commit.returncode != 0:
            sys.stderr.write(f"[vault_push] commit failed: {commit.stderr}\n"); return False
        push = git("push", "origin", "HEAD")
        if push.returncode != 0:
            sys.stderr.write(f"[vault_push] push failed: {push.stderr}\n"); return False
        return True
    except Exception as e:  # subprocess timeout etc. — cron must survive
        sys.stderr.write(f"[vault_push] {type(e).__name__}: {e}\n")
        return False
