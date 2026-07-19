#!/usr/bin/env python3
"""
Export Zotero items to CSV with Clawdia summaries included.

Supports collection-level export, whole-library export, and filtering
by triage tag for sharing curated subsets.

Usage:
    # Export one collection
    python3 zotero_export_csv.py --collection "Lit Review" ~/Desktop/lit-review.csv

    # Export everything
    python3 zotero_export_csv.py --all ~/Desktop/all-papers.csv

    # Export only 🔴-core papers from whole library
    python3 zotero_export_csv.py --all --triage "🔴-core" ~/Desktop/core-papers.csv

    # Export only 🟡-context papers from a collection
    python3 zotero_export_csv.py --collection "Lit Review" --triage "🟡-context" ~/Desktop/context.csv

Setup:
    Requires ZOTERO_USER_ID and ZOTERO_API_KEY environment variables.

Author: Anna Russell
"""

import os
import csv
import re
import sys
import argparse
from pyzotero import zotero

ZOTERO_USER_ID = int(os.environ.get('ZOTERO_USER_ID', '19185138'))
ZOTERO_API_KEY = os.environ.get('ZOTERO_API_KEY', '')

if not ZOTERO_API_KEY:
    print("ERROR: Set ZOTERO_API_KEY environment variable")
    sys.exit(1)

zot = zotero.Zotero(ZOTERO_USER_ID, "user", ZOTERO_API_KEY)


# ============================================================================
# HELPERS
# ============================================================================

def strip_html(html_text: str) -> str:
    """Quick HTML to plain text conversion."""
    text = re.sub(r'<[^>]+>', ' ', html_text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def find_collection_by_name(name: str):
    """Find a collection's key by its name (case-insensitive)."""
    collections = zot.collections()
    for c in collections:
        if c['data']['name'].lower() == name.lower():
            return c['key']
    return None


def extract_item_data(item: dict) -> dict:
    """Extract the metadata fields we want from a Zotero item."""
    data = item['data']
    key = item['key']

    title = data.get('title', '')

    authors = []
    for c in data.get('creators', []):
        if c.get('lastName'):
            first = c.get('firstName', '')
            authors.append(f"{c['lastName']}, {first}" if first else c['lastName'])
        elif c.get('name'):
            authors.append(c['name'])
    authors_str = "; ".join(authors)

    year = ''
    date = data.get('date', '')
    year_match = re.search(r'\b(19|20)\d{2}\b', date)
    if year_match:
        year = year_match.group(0)

    item_type = data.get('itemType', '')
    tags_list = [t['tag'] for t in data.get('tags', [])]
    tags_str = ", ".join(tags_list)
    url = data.get('url', '')
    doi = data.get('DOI', '')
    abstract = data.get('abstractNote', '')
    publication = (
            data.get('publicationTitle')
            or data.get('bookTitle')
            or data.get('proceedingsTitle')
            or data.get('journalAbbreviation')
            or ''
    )

    return {
        'key': key,
        'title': title,
        'authors': authors_str,
        'year': year,
        'item_type': item_type,
        'publication': publication,
        'tags': tags_str,
        'tags_list': tags_list,
        'abstract': abstract,
        'url': url,
        'doi': doi,
    }


def extract_notes(item_key: str) -> tuple:
    """Get Clawdia summary and other notes for an item.

    Returns: (clawdia_summary, other_notes_joined)
    """
    children = zot.children(item_key)
    clawdia_summary = ''
    other_notes = []

    for child in children:
        cdata = child['data']
        if cdata.get('itemType') == 'note':
            note_text = strip_html(cdata.get('note', ''))
            is_clawdia = any(
                t.get('tag') == 'clawdia-generated'
                for t in cdata.get('tags', [])
            )
            if is_clawdia:
                clawdia_summary = note_text
            else:
                other_notes.append(note_text)

    return clawdia_summary, " | ".join(other_notes)


def passes_triage_filter(tags_list: list, triage_filter: str) -> bool:
    """Check if item passes the optional triage filter."""
    if not triage_filter:
        return True
    return triage_filter in tags_list


# ============================================================================
# EXPORT FUNCTIONS
# ============================================================================

CSV_HEADERS = [
    'Key', 'Title', 'Authors', 'Year', 'Item Type', 'Publication',
    'Tags', 'Clawdia Summary', 'Other Notes', 'Abstract', 'URL', 'DOI'
]


def write_csv_row(writer, item_data: dict, clawdia_summary: str, other_notes: str):
    """Write a single row to the CSV."""
    writer.writerow([
        item_data['key'],
        item_data['title'],
        item_data['authors'],
        item_data['year'],
        item_data['item_type'],
        item_data['publication'],
        item_data['tags'],
        clawdia_summary,
        other_notes,
        item_data['abstract'],
        item_data['url'],
        item_data['doi'],
    ])


def export_collection(collection_name: str, output_path: str, triage_filter: str = None):
    """Export a specific collection to CSV."""
    collection_key = find_collection_by_name(collection_name)
    if not collection_key:
        print(f"✗ Collection '{collection_name}' not found")
        return

    print(f"📚 Fetching items from '{collection_name}'...")
    items = zot.everything(zot.collection_items_top(collection_key))
    print(f"✓ Found {len(items)} items")

    if triage_filter:
        print(f"🔍 Filtering by triage: {triage_filter}")

    process_and_write(items, output_path, triage_filter)


def export_all_items(output_path: str, triage_filter: str = None):
    """Export every top-level item in the library to CSV."""
    print("📚 Fetching all items from library (this may take a minute)...")
    items = zot.everything(zot.top())
    print(f"✓ Found {len(items)} items total")

    if triage_filter:
        print(f"🔍 Filtering by triage: {triage_filter}")

    process_and_write(items, output_path, triage_filter)


def process_and_write(items: list, output_path: str, triage_filter: str = None):
    """Process items and write CSV with progress reporting."""
    written = 0
    filtered_out = 0

    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(CSV_HEADERS)

        for i, item in enumerate(items, 1):
            if i % 25 == 0:
                print(f"  Processing {i}/{len(items)}...")

            item_data = extract_item_data(item)

            if not passes_triage_filter(item_data['tags_list'], triage_filter):
                filtered_out += 1
                continue

            try:
                clawdia_summary, other_notes = extract_notes(item_data['key'])
            except Exception as e:
                print(f"  ! Could not get notes for {item_data['title'][:50]}: {e}")
                clawdia_summary, other_notes = '', ''

            write_csv_row(writer, item_data, clawdia_summary, other_notes)
            written += 1

    print(f"\n{'=' * 60}")
    print(f"✓ Exported {written} items to {output_path}")
    if filtered_out:
        print(f"  ({filtered_out} items filtered out by triage filter)")
    print(f"{'=' * 60}\n")


# ============================================================================
# CLI
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Export Zotero items to CSV with Clawdia summaries"
    )

    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument(
        "--collection",
        type=str,
        help="Name of Zotero collection to export"
    )
    source_group.add_argument(
        "--all",
        action="store_true",
        help="Export all top-level items in the library"
    )

    parser.add_argument(
        "output",
        help="Output CSV file path (e.g. ~/Desktop/papers.csv)"
    )

    parser.add_argument(
        "--triage",
        type=str,
        choices=['🔴-core', '🟡-context', '🟢-background', '⚫-drop'],
        help="Only export papers with this triage tag"
    )

    args = parser.parse_args()

    output_path = os.path.expanduser(args.output)

    if args.all:
        export_all_items(output_path, args.triage)
    else:
        export_collection(args.collection, output_path, args.triage)


if __name__ == "__main__":
    main()