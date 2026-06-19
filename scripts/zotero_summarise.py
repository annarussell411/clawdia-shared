#!/usr/bin/env python3
"""
Zotero summarisation script for Clawdia (v3 - Pyzotero edition).

Reads papers in a specified Zotero collection, generates a 4-sentence
structured summary via Clawdia, posts the summary as a child note in
Zotero, and applies triage and category tags.

Uses the Zotero Web API via Pyzotero (the local API is read-only).
Your library must be synced to Zotero's cloud for this to work.

SAFETY GUARANTEES:
    - Existing notes are never modified or deleted
    - Existing tags on papers are preserved (only new tags added)
    - Papers already tagged 'summarised' are skipped entirely
    - The --setup-colours command REPLACES the tag colour scheme

Usage:
    python3 zotero_summarise.py <collection_name>
    python3 zotero_summarise.py --list-collections
    python3 zotero_summarise.py --setup-colours
    python3 zotero_summarise.py <collection_name> --dry-run

Setup:
    1. Install: pip install pyzotero pypdf
    2. Set environment variables:
       export ZOTERO_USER_ID=19185138
       export ZOTERO_API_KEY=your_key_from_zotero_settings_keys
       Or edit the CONFIG block below.

Author: Anna Russell
"""

import os
import sys
import json
import argparse
import subprocess
import uuid
from pathlib import Path
from typing import Optional

from pyzotero import zotero

try:
    from pypdf import PdfReader
except ImportError:
    print("Install pypdf: pip install pypdf")
    sys.exit(1)

# ============================================================================
# CONFIG
# ============================================================================

# Zotero credentials - prefer environment variables, fall back to hardcoded
ZOTERO_USER_ID = int(os.environ.get('ZOTERO_USER_ID', '19185138'))
ZOTERO_API_KEY = os.environ.get('ZOTERO_API_KEY', '')

if not ZOTERO_API_KEY:
    print("ERROR: Set ZOTERO_API_KEY environment variable")
    print("Get a key at https://www.zotero.org/settings/keys")
    print("Then: export ZOTERO_API_KEY=your_key_here")
    sys.exit(1)

# Skip these tags - means already processed
ALREADY_SUMMARISED_TAG = "summarised"

# Tag colour scheme - run --setup-colours once to apply
# WARNING: applying this REPLACES the tag colour scheme for the library
TAG_COLOURS = [
    # Triage categories (Clawdia suggests, you confirm)
    {"name": "🔴-core", "color": "#FF4136"},  # red
    {"name": "🟡-context", "color": "#FFDC00"},  # yellow
    {"name": "🟢-background", "color": "#2ECC40"},  # green
    {"name": "⚫-drop", "color": "#85144B"},  # maroon

    # Reading depth progression (your manual tags)
    {"name": "skimmed", "color": "#7FDBFF"},  # light blue
    {"name": "READ", "color": "#0074D9"},  # blue (existing)
    {"name": "deep-read", "color": "#001F3F"},  # navy

    # Process tag (Clawdia adds this)
    {"name": "summarised", "color": "#39CCCC"},  # teal

    # Quality/flag tags (Clawdia suggests, you confirm)
    {"name": "high-potential", "color": "#FF851B"},  # orange
    {"name": "method-relevant", "color": "#3D9970"},  # olive
    {"name": "needs-supervisor", "color": "#B10DC9"},  # purple
    {"name": "off-topic-but-interesting", "color": "#AAAAAA"},  # grey
    {"name": "economic-alignment", "color": "#F012BE"},  # magenta
]

# ============================================================================
# SUMMARY PROMPT
# ============================================================================

SUMMARY_PROMPT = """You are summarising an academic paper for Anna, a PhD researcher 
at QUT through the CSIRO NGGP partnership with the Australian Sports Commission. 
Her PhD focuses on value alignment in agentic multi-agent AI systems within 
sociotechnical frameworks, using elite youth athlete support networks as the 
empirical context. Key theoretical anchors: van de Poel (2020), Kudina and van de 
Poel (2024), constructs of dynamic alignment, epistemic integrity, expertise-adaptive 
communication, and trust calibration.

Read the paper text below and produce EXACTLY a 4-sentence summary in this structure:

Sentence 1-2: What the paper is about (the core question and contribution).

Sentence 3: What aspect of this paper relates to alignment, and whether it deals with 
            model alignment, agent alignment, or multi-agent alignment specifically.

Sentence 4: Paper type (theoretical / experimental / survey or review / position paper), 
            approximate length (number of pages if visible from text), and year first published.

Format as plain text only - no markdown, no headers, just the four sentences as a paragraph.

Then on a new line, suggest a triage category according to these criteria:

TRIAGE: 🔴-core | 🟡-context | 🟢-background | ⚫-drop

Triage criteria:
- 🔴-core: Directly addresses value alignment, dynamic alignment, epistemic integrity, 
  expertise-adaptive communication, trust calibration, multi-agent alignment, or 
  sociotechnical AI frameworks (van de Poel, Kudina). Will likely be cited in the thesis.
- 🟡-context: Provides theoretical or methodological support for the framing - action 
  research, sociotechnical systems, AI alignment more broadly. Useful supporting reference.
- 🟢-background: Provides general context on AI alignment, multi-agent systems, or 
  relevant empirical contexts. Useful background but won't be central.
- ⚫-drop: Low quality, off-topic to the point of not being useful, or covers ground 
  already covered better elsewhere.

Then on another new line, list any of these additional tags that apply (comma separated, 
or "none"):

TAGS: high-potential, method-relevant, needs-supervisor, off-topic-but-interesting, economic-alignment

Additional tag criteria:
- high-potential: Novel theoretical OR quantitative methods, OR interdisciplinary 
  approaches to alignment. Flag for early deep read.
- method-relevant: Uses action research, sociotechnical analysis, or multi-agent 
  evaluation methods Anna might adopt or adapt.
- needs-supervisor: Raises a framing decision or research question worth discussing 
  with her supervisors before incorporating.
- off-topic-but-interesting: Interesting paper but not directly relevant to Anna's 
  thesis. Use this when the paper has scholarly merit but is outside her research 
  scope (separate from ⚫-drop which is for low value or poor quality).
- economic-alignment: Multi-agent alignment via market mechanisms, game theory, 
  Nash equilibrium, prisoner's dilemma, bidding, auctions, or other economic theory 
  approaches to coordinating agents.

Paper text follows:
---
{paper_text}
---"""

# ============================================================================
# ZOTERO CLIENT
# ============================================================================

zot = zotero.Zotero(ZOTERO_USER_ID, "user", ZOTERO_API_KEY)


# ============================================================================
# COLLECTION + ITEM HELPERS
# ============================================================================

def list_collections():
    """List all top-level collections."""
    collections = zot.collections()
    print(f"\nFound {len(collections)} collections:\n")
    for c in collections:
        name = c['data']['name']
        key = c['key']
        item_count = c['meta'].get('numItems', '?')
        print(f"  {key}  |  {name}  ({item_count} items)")
    print()
    return collections


def find_collection_by_name(name: str):
    """Find a collection's key by its name (case-insensitive)."""
    collections = zot.collections()
    for c in collections:
        if c['data']['name'].lower() == name.lower():
            return c['key']
    return None


def get_collection_items(collection_key: str):
    """Get all top-level items (papers) in a collection."""
    return zot.collection_items_top(collection_key)


def get_pdf_attachment_path(item_key: str) -> Optional[Path]:
    """Find the local PDF file path for an item's PDF attachment."""
    children = zot.children(item_key)
    for child in children:
        data = child['data']
        if (data.get('itemType') == 'attachment'
                and data.get('contentType') == 'application/pdf'):
            storage_dir = Path.home() / "Zotero" / "storage" / child['key']
            if storage_dir.exists():
                pdfs = list(storage_dir.glob("*.pdf"))
                if pdfs:
                    return pdfs[0]
    return None


def item_has_tag(item: dict, tag: str) -> bool:
    """Check if an item already has a given tag."""
    tags = item['data'].get('tags', [])
    return any(t.get('tag') == tag for t in tags)


# ============================================================================
# PDF READING
# ============================================================================

def extract_pdf_text(pdf_path: Path, max_chars: int = 50000) -> str:
    """Extract text from a PDF, capped at max_chars to control token cost."""
    try:
        reader = PdfReader(str(pdf_path))
        text_parts = []
        total_chars = 0
        for page in reader.pages:
            page_text = page.extract_text() or ""
            text_parts.append(page_text)
            total_chars += len(page_text)
            if total_chars >= max_chars:
                break
        #return "\n".join(text_parts)[:max_chars]
        full_text = "\n".join(text_parts)
    # Strip null bytes and other control chars that break subprocess
        full_text = ''.join(c for c in full_text if c == '\n' or c == '\t' or ord(c) >= 32)
        return full_text[:max_chars]
    except Exception as e:
        print(f"  ! Could not read PDF: {e}")
        return ""


# ============================================================================
# SUMMARY GENERATION VIA OPENCLAW CLI
# ============================================================================

def generate_summary(paper_text: str) -> dict:
    """
    Generate a 4-sentence summary by shelling out to openclaw agent CLI.
    Uses a fresh session key each time to avoid Clawdia caching prior summaries.
    Returns: {summary: str, triage: str, tags: list[str]}
    """
    prompt = SUMMARY_PROMPT.format(paper_text=paper_text)

    try:
        session_key = f"agent:main:zotero-{uuid.uuid4().hex[:8]}"

        result = subprocess.run(
            ["openclaw", "agent", "--agent", "main",
             "--session-key", session_key, "-m", prompt],
            capture_output=True,
            text=True,
            timeout=180  # 3 min per paper
        )

        if result.returncode != 0:
            print(f"  ! openclaw returned error: {result.stderr[:200]}")
            return {"summary": "", "triage": "🟢-background", "tags": []}

        response_text = result.stdout.strip()
        response_text = clean_openclaw_output(response_text)
        return parse_summary_response(response_text)

    except subprocess.TimeoutExpired:
        print("  ! Summary generation timed out")
        return {"summary": "", "triage": "🟢-background", "tags": []}
    except FileNotFoundError:
        print("  ! openclaw CLI not found - is it installed?")
        return {"summary": "", "triage": "🟢-background", "tags": []}
    except Exception as e:
        print(f"  ! Summary generation failed: {e}")
        return {"summary": "", "triage": "🟢-background", "tags": []}


def clean_openclaw_output(text: str) -> str:
    """Strip openclaw's decorative banners and status lines from output."""
    lines = text.split('\n')
    cleaned_lines = []
    skip_patterns = [
        '🦞 OpenClaw',
        '[plugins]',
        'plugins.allow',
        '│',
        '◇',
        'Config warnings:',
    ]
    for line in lines:
        if any(pattern in line for pattern in skip_patterns):
            continue
        cleaned_lines.append(line)
    return '\n'.join(cleaned_lines).strip()


def parse_summary_response(response: str) -> dict:
    """Parse the structured response into summary, triage, and tags."""
    lines = response.strip().split('\n')

    summary_lines = []
    triage = "🟢-background"
    tags = []

    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith("TRIAGE:"):
            triage_value = line.replace("TRIAGE:", "").strip()
            triage = triage_value.split('|')[0].strip()
        elif line.startswith("TAGS:"):
            tags_value = line.replace("TAGS:", "").strip()
            if tags_value.lower() != "none":
                tags = [t.strip() for t in tags_value.split(',') if t.strip()]
        else:
            summary_lines.append(line)

    return {
        "summary": " ".join(summary_lines),
        "triage": triage,
        "tags": tags
    }


# ============================================================================
# NOTE + TAG WRITING (via Pyzotero)
# ============================================================================

def post_summary_note(parent_key: str, summary_text: str, triage: str, tags: list):
    """Post a summary as a NEW child note attached to the parent item.

    SAFETY: This only creates new notes. Existing notes are unaffected.
    """
    tag_list_html = ", ".join(tags) if tags else "none"

    html = (
        f"<p><strong>Clawdia summary</strong></p>"
        f"<p>{summary_text}</p>"
        f"<p><strong>Suggested triage:</strong> {triage}</p>"
        f"<p><strong>Suggested additional tags:</strong> {tag_list_html}</p>"
    )

    # Get a fresh note template, populate it, and create the item
    template = zot.item_template('note')
    template['note'] = html
    template['tags'] = [{'tag': 'clawdia-generated'}]

    return zot.create_items([template], parentid=parent_key)


def add_tags_to_paper(item_key: str, new_tags: list):
    """Add tags to a paper item.

    SAFETY: Existing tags are preserved. Only new tags (not already present)
    are added. No tags are removed.
    """
    item = zot.item(item_key)
    existing_tags = item['data'].get('tags', [])
    existing_tag_names = {t.get('tag') for t in existing_tags}

    tags_changed = False
    for tag in new_tags:
        if tag and tag not in existing_tag_names:
            existing_tags.append({"tag": tag, "type": 0})
            existing_tag_names.add(tag)
            tags_changed = True

    if tags_changed:
        item['data']['tags'] = existing_tags
        zot.update_item(item)


# ============================================================================
# TAG COLOUR SETUP
# ============================================================================

def setup_tag_colours():
    """Apply the colour scheme to library tags.

    Note: tag colours are a library-level setting. Pyzotero exposes this
    via the settings endpoint.
    """
    print("\n⚠️  This will REPLACE the existing tag colour scheme.")
    print("Existing READ tag colour will be preserved by including it in the scheme.")
    confirm = input("Continue? (yes/no): ").strip().lower()
    if confirm != "yes":
        print("Cancelled.")
        return

    # Pyzotero doesn't have a direct method for tagColors settings,
    # but we can use the underlying request mechanism
    import requests

    url = f"https://api.zotero.org/users/{ZOTERO_USER_ID}/settings/tagColors"
    headers = {
        "Zotero-API-Key": ZOTERO_API_KEY,
        "Content-Type": "application/json"
    }

    # Get current version
    r = requests.get(url, headers=headers)
    if r.status_code == 200:
        version = r.json().get('version', 0)
    else:
        version = 0

    payload = {"value": TAG_COLOURS, "version": version}
    r = requests.put(url, json=payload, headers=headers)

    if r.status_code in (200, 204):
        print(f"✓ Tag colours applied ({len(TAG_COLOURS)} tags)")
        print("Note: may need to restart Zotero to see colours in UI")
    else:
        print(f"✗ Failed with status {r.status_code}: {r.text[:200]}")


# ============================================================================
# MAIN WORKFLOW
# ============================================================================

def summarise_collection(collection_name: str, dry_run: bool = False):
    """Process all unsummarised papers in a collection."""

    print(f"\n📚 Looking up collection: {collection_name}")
    collection_key = find_collection_by_name(collection_name)

    if not collection_key:
        print(f"✗ Collection '{collection_name}' not found.")
        print("Run --list-collections to see available collections.")
        return

    print(f"✓ Found collection key: {collection_key}")

    if dry_run:
        print("🧪 DRY RUN MODE - no changes will be made\n")

    print("\n📋 Fetching items...")
    items = get_collection_items(collection_key)
    print(f"✓ Found {len(items)} items\n")

    processed = 0
    skipped = 0
    failed = 0

    for i, item in enumerate(items, 1):
        title = item['data'].get('title', 'Untitled')
        key = item['key']

        print(f"[{i}/{len(items)}] {title[:80]}")

        if item_has_tag(item, ALREADY_SUMMARISED_TAG):
            print("  ⊘ Already summarised, skipping")
            skipped += 1
            continue

        pdf_path = get_pdf_attachment_path(key)
        if not pdf_path:
            print("  ! No PDF attachment found, skipping")
            failed += 1
            continue

        print(f"  📖 Reading {pdf_path.name}")
        paper_text = extract_pdf_text(pdf_path)
        if not paper_text:
            print("  ! Could not extract text")
            failed += 1
            continue

        print("  🤖 Generating summary...")
        result = generate_summary(paper_text)

        if not result['summary']:
            print("  ! Summary generation failed")
            failed += 1
            continue

        print(f"  📝 Summary: {result['summary']}")
        print(f"  🏷️  Triage: {result['triage']}")
        if result['tags']:
            print(f"  🏷️  Tags: {', '.join(result['tags'])}")

        if dry_run:
            print("  🧪 DRY RUN - skipping Zotero write")
            processed += 1
            continue

        print("  📝 Posting note to Zotero...")
        try:
            post_summary_note(
                key,
                result['summary'],
                result['triage'],
                result.get('tags', [])
            )
        except Exception as e:
            print(f"  ! Note posting failed: {e}")
            failed += 1
            continue

        tags_to_add = [ALREADY_SUMMARISED_TAG, result['triage']]
        tags_to_add.extend(result.get('tags', []))
        try:
            add_tags_to_paper(key, tags_to_add)
            print(f"  ✓ Tagged: {', '.join(tags_to_add)}")
        except Exception as e:
            print(f"  ! Tagging failed: {e}")

        processed += 1

    print(f"\n{'=' * 60}")
    print(f"Summary: {processed} processed, {skipped} skipped, {failed} failed")
    print(f"{'=' * 60}\n")


# ============================================================================
# CLI
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Summarise a Zotero collection via Clawdia"
    )
    parser.add_argument(
        "collection",
        nargs="?",
        help="Name of Zotero collection to summarise"
    )
    parser.add_argument(
        "--list-collections",
        action="store_true",
        help="List all available collections"
    )
    parser.add_argument(
        "--setup-colours",
        action="store_true",
        help="Apply tag colour scheme (WARNING: replaces existing scheme)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate summaries and print them but do not write to Zotero"
    )

    args = parser.parse_args()

    if args.list_collections:
        list_collections()
    elif args.setup_colours:
        setup_tag_colours()
    elif args.collection:
        summarise_collection(args.collection, dry_run=args.dry_run)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
