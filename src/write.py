from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

import yaml


def kebab_slug(value: str) -> str:
    lowered = value.lower().strip()
    cleaned = re.sub(r"[^a-z0-9]+", "-", lowered)
    return cleaned.strip("-")


def _yaml_frontmatter(data: dict) -> str:
    body = yaml.safe_dump(data, sort_keys=False, allow_unicode=True).strip()
    return f"---\n{body}\n---\n"


def write_source_page(
    *,
    vault: Path,
    fetch: dict,
    extraction: dict,
    creator_slug: str,
    date_ingested: str,
) -> Path:
    video_slug = kebab_slug(fetch["title"])
    filename = f"{creator_slug}--{video_slug}.md"
    path = vault / "wiki" / "sources" / filename
    path.parent.mkdir(parents=True, exist_ok=True)

    fm = {
        "title": fetch["title"],
        "type": "source",
        "source_type": "video",
        "source_platform": "youtube",
        "video_id": fetch["video_id"],
        "video_url": fetch["webpage_url"],
        "creator": f"[[{creator_slug}]]",
        "published_at": fetch["published_at"],
        "duration_seconds": fetch["duration_seconds"],
        "date_ingested": date_ingested,
        "raw_path": f"raw/youtube/{fetch['video_id']}.transcript.txt",
        "categories": extraction["categories"],
        "domain": extraction["domain"],
        "tags": extraction["tags"],
    }
    parts = [
        _yaml_frontmatter(fm),
        "\n## Session Summary\n",
        extraction["session_summary"].strip() + "\n",
        "\n## Instructions & How-To\n",
        extraction["instructions_and_howto"].strip() + "\n",
        "\n## Resources Mentioned\n",
    ]
    if extraction["resources"]:
        for res in extraction["resources"]:
            parts.append(
                f"- [{res['title']}]({res['url']}) — {res['description']}\n"
            )
    else:
        parts.append("_None._\n")
    parts.append("\n## Key Takeaways\n")
    for t in extraction["key_takeaways"]:
        parts.append(f"- {t}\n")
    parts.append("\n## Connections\n")
    if extraction["connections"]:
        for c in extraction["connections"]:
            parts.append(f"- [[{c['target']}]] — {c['note']}\n")
    else:
        parts.append("_None._\n")
    path.write_text("".join(parts))
    return path


_CREATOR_BIO_PLACEHOLDER = "_First sighting — bio to be appended as more videos are ingested._"


def upsert_creator_page(
    *,
    vault: Path,
    channel: str,
    channel_url: str,
    channel_id: str,
    video_title: str,
    video_slug: str,
    video_summary: str,
    video_published_at: str,
    video_domain: str,
    categories: list[str],
    creator_bio_additions: str,
    today: str,
) -> tuple[str, Path]:
    creator_slug = f"creator-{kebab_slug(channel)}"
    path = vault / "wiki" / "entities" / f"{creator_slug}.md"
    path.parent.mkdir(parents=True, exist_ok=True)

    source_line = (
        f"- [[{creator_slug}--{video_slug}]] — {video_published_at} — "
        f"{video_summary.splitlines()[0] if video_summary else ''}"
    )

    if not path.exists():
        fm = {
            "title": channel,
            "type": "entity",
            "entity_type": "creator",
            "creator_platform": "youtube",
            "channel_url": channel_url,
            "channel_id": channel_id,
            "domain": [video_domain],
            "created": today,
            "updated": today,
            "source_count": 1,
            "tags": ["creator"],
        }
        bio = creator_bio_additions.strip() or _CREATOR_BIO_PLACEHOLDER
        themes = ", ".join(categories) or "_none yet_"
        content = (
            _yaml_frontmatter(fm)
            + f"\n## About\n{bio}\n\n## Themes\n{themes}\n\n## Sources\n{source_line}\n"
        )
        path.write_text(content)
        return creator_slug, path

    existing = path.read_text()
    fm_end = existing.index("\n---\n", 4)
    fm = yaml.safe_load(existing[4:fm_end])
    fm["updated"] = today
    fm["source_count"] = int(fm.get("source_count", 0)) + 1
    domains = set(fm.get("domain") or [])
    domains.add(video_domain)
    fm["domain"] = sorted(domains)
    body = existing[fm_end + 5:]

    if creator_bio_additions.strip():
        addition = f"_Added {today}:_ {creator_bio_additions.strip()}\n"
        about_idx = body.index("## About\n") + len("## About\n")
        next_header = body.index("\n## ", about_idx)
        about_body = body[about_idx:next_header]
        if _CREATOR_BIO_PLACEHOLDER in about_body:
            about_body = about_body.replace(_CREATOR_BIO_PLACEHOLDER, "").strip()
            about_body = (about_body + "\n\n" if about_body else "") + addition
        else:
            about_body = about_body.rstrip() + "\n\n" + addition
        body = body[:about_idx] + about_body + body[next_header:]

    themes_header = "## Themes\n"
    themes_start = body.index(themes_header) + len(themes_header)
    themes_end = body.index("\n## ", themes_start)
    current_themes = {t.strip() for t in body[themes_start:themes_end].split(",")}
    current_themes.discard("_none yet_")
    current_themes.update(categories)
    new_themes_block = ", ".join(sorted(t for t in current_themes if t))
    body = body[:themes_start] + new_themes_block + body[themes_end:]

    body = body.rstrip() + "\n" + source_line + "\n"
    path.write_text(_yaml_frontmatter(fm) + body)
    return creator_slug, path


# ---------------------------------------------------------------------------
# Task 22: resources-index upsert
# ---------------------------------------------------------------------------
_RESOURCE_GROUPS_ORDERED = ("Tools", "Documentation", "Articles", "Uncategorised")


def _parse_resources_index(text: str) -> tuple[dict, dict[str, list[dict]]]:
    if not text.startswith("---\n"):
        return {"title": "Resources Index", "type": "index",
                "created": "", "updated": "", "entry_count": 0}, {g: [] for g in _RESOURCE_GROUPS_ORDERED}
    fm_end = text.index("\n---\n", 4)
    fm = yaml.safe_load(text[4:fm_end])
    body = text[fm_end + 5:]

    groups: dict[str, list[dict]] = {g: [] for g in _RESOURCE_GROUPS_ORDERED}
    current: str | None = None
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            current = stripped[3:].strip()
            continue
        if current is None or not stripped.startswith("- "):
            continue
        try:
            body_part = stripped[2:]
            url_part, title_part, desc_part, mention_part = body_part.split(" | ", 3)
            slugs = re.findall(r"\[\[([^\]]+)\]\]", mention_part)
            groups.setdefault(current, []).append({
                "url": url_part.strip(),
                "title": title_part.strip(),
                "description": desc_part.strip(),
                "sources": slugs,
            })
        except ValueError:
            continue
    return fm, groups


def _render_resources_index(fm: dict, groups: dict[str, list[dict]]) -> str:
    parts = [_yaml_frontmatter(fm)]
    for group in _RESOURCE_GROUPS_ORDERED:
        entries = groups.get(group) or []
        if not entries:
            continue
        parts.append(f"\n## {group}\n")
        for e in entries:
            mentions = ", ".join(f"[[{s}]]" for s in e["sources"])
            parts.append(
                f"- {e['url']} | {e['title']} | {e['description']} | {mentions}\n"
            )
    return "".join(parts)


def upsert_resources_index(
    *,
    vault: Path,
    resources: list[dict],
    source_slug: str,
    today: str,
) -> Path:
    path = vault / "wiki" / "sources" / "resources-index.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text() if path.exists() else ""
    fm, groups = _parse_resources_index(existing)
    if not fm.get("created"):
        fm["created"] = today
    fm["updated"] = today

    for res in resources:
        group = res["group"] if res["group"] in _RESOURCE_GROUPS_ORDERED else "Uncategorised"
        existing_entry = next(
            (e for e in groups.get(group, []) if e["url"] == res["url"]), None
        )
        if existing_entry:
            if source_slug not in existing_entry["sources"]:
                existing_entry["sources"].append(source_slug)
        else:
            groups.setdefault(group, []).append({
                "url": res["url"],
                "title": res["title"],
                "description": res["description"],
                "sources": [source_slug],
            })

    fm["entry_count"] = sum(
        len(groups.get(g) or []) for g in _RESOURCE_GROUPS_ORDERED
    )
    path.write_text(_render_resources_index(fm, groups))
    return path


# ---------------------------------------------------------------------------
# Task 23: index.md and log.md appenders
# ---------------------------------------------------------------------------
def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".tmp.", dir=path.parent, text=True)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def append_index_entries(
    *,
    vault: Path,
    source_slug: str,
    source_title: str,
    creator_slug: str,
    creator_name: str,
    creator_is_new: bool,
) -> None:
    path = vault / "index.md"
    text = path.read_text() if path.exists() else (
        "# Index\n\n## Entities\n\n## Concepts\n\n## Sources\n\n## Analyses\n"
    )

    def append_under(section: str, line: str) -> str:
        header = f"## {section}\n"
        idx = text.index(header) + len(header)
        next_section = text.find("\n## ", idx)
        insert_at = next_section if next_section != -1 else len(text)
        return text[:insert_at].rstrip() + "\n" + line + "\n" + text[insert_at:]

    if creator_is_new:
        text = append_under("Entities", f"- [[{creator_slug}]] — {creator_name}")
    text = append_under("Sources", f"- [[{source_slug}]] — {source_title}")
    _atomic_write(path, text)


def append_log_entry(*, vault: Path, timestamp: str, message: str) -> None:
    path = vault / "log.md"
    existing = path.read_text() if path.exists() else "# Log\n"
    line = f"- {timestamp} — {message}\n"
    path.write_text(existing.rstrip() + "\n" + line)
