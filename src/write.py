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
