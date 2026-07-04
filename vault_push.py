"""Commit+push the AI Learnings vault after each ingest run — fixes the
uncommitted-vault gotcha at the source (spec §3a). Never raises.

Standalone by design (no src/ imports) so cron can exercise it via
`python -c "from vault_push import push_vault; ..."`. Diagnostics use the
same stdlib-logging idiom as src/main.py; with no handler configured
(standalone use) logging's last-resort handler still lands them on stderr.
"""
import logging
import subprocess

logger = logging.getLogger(__name__)

WIKI_ROOT = "/Users/steven/Vibe Projects/wiki-knowledge-interface"
SUBPATH = "vaults/AI Learnings"


def push_vault(wiki_root: str = WIKI_ROOT, subpath: str = SUBPATH) -> bool:
    def git(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", "-C", wiki_root, *args],
                              capture_output=True, text=True, timeout=120)

    def push() -> bool:
        p = git("push", "origin", "HEAD")
        if p.returncode != 0:
            logger.error("[vault_push] push failed: %s", p.stderr)
            return False
        return True

    try:
        status = git("status", "--porcelain", "--", subpath)
        if status.returncode != 0:
            logger.error("[vault_push] status failed: %s", status.stderr)
            return False
        if not status.stdout.strip():
            # Nothing new to commit — but a previous run may have committed
            # and then failed to push (transient network). Clean porcelain
            # alone would strand that commit forever, so check whether we
            # are ahead of upstream; if so (or if upstream is unknowable,
            # e.g. no tracking ref), attempt the push anyway.
            ahead = git("rev-list", "--count", "@{u}..HEAD")
            if ahead.returncode != 0 or ahead.stdout.strip() != "0":
                return push()
            return True  # clean and in sync with upstream
        if git("add", "--", subpath).returncode != 0:
            return False
        # Pathspec-scoped commit: takes ONLY changes under subpath, even if
        # unrelated files were already staged before this ran — those stay
        # staged and uncommitted.
        commit = git("commit", "-m", "yt-ingest: vault update (auto)", "--", subpath)
        if commit.returncode != 0:
            logger.error("[vault_push] commit failed: %s", commit.stderr)
            return False
        return push()
    except Exception as e:  # subprocess timeout etc. — cron must survive
        logger.error("[vault_push] %s: %s", type(e).__name__, e)
        return False
