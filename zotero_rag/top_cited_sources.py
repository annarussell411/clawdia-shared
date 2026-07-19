#!/usr/bin/env python3
"""
Zotero Reference Graph — Top Cited Sources
Analyses the citation cache to find the most frequently cited sources
across your library, including external sources (knowledge gaps).

Usage: python3 top_cited_sources.py [--top N] [--json] [--gaps-only]
"""
import json
import sys
import re
from pathlib import Path
from collections import Counter

WORKSPACE = Path(__file__).parent
CACHE_FILE = WORKSPACE / "citation_cache.json"


def load_cache():
    with open(CACHE_FILE) as f:
        return json.load(f)


def load_library_dois():
    """Load DOIs already in the Zotero library."""
    import sqlite3, shutil
    zotero_db = Path.home() / "Zotero" / "zotero.sqlite"
    tmp = Path("/tmp/zotero_toprefs_check.sqlite")
    shutil.copy2(zotero_db, tmp)
    conn = sqlite3.connect(str(tmp))
    library_dois = set()
    for row in conn.execute("""
        SELECT DISTINCT LOWER(idv.value)
        FROM itemData id
        JOIN itemDataValues idv ON id.valueID = idv.valueID
        WHERE id.fieldID = 59 AND idv.value IS NOT NULL
    """).fetchall():
        library_dois.add(row[0].strip())
    conn.close()
    return library_dois


def normalize_key(ref):
    """Build a normalized deduplication key from DOI or title."""
    doi = ref.get('doi', '').strip().lower()
    title = ref.get('title', '').strip()
    if doi and len(doi) > 5:
        return f'doi:{doi}'
    if title and len(title) > 10:
        nt = re.sub(r'[^a-z0-9]', '', title.lower())[:60]
        return f'title:{nt}'
    return None


def clean_authors(authors):
    """Reconstruct author string from character-split Crossref output."""
    if not authors:
        return ""
    # Crossref sometimes returns author surnames split into individual chars
    # e.g. ['B', 'a', 'r', 't', 'o'] instead of ['Barto']
    if all(len(a) == 1 for a in authors) and len(authors) > 2:
        # It's character-split — join them
        return ''.join(authors)
    if all(isinstance(a, str) and len(a) <= 2 for a in authors):
        return ''.join(authors)
    return '; '.join(str(a) for a in authors)


def format_source(ref, in_library):
    """Format a reference as a clean citation string."""
    title = ref.get('title', '') or '[no title]'
    author = ref.get('first_author', '')
    year = ref.get('year', '')
    journal = ref.get('journal', '')
    doi = ref.get('doi', '')

    # Build the citation
    parts = []

    # Author
    if author:
        author_clean = clean_authors([author]) if isinstance(author, str) and len(author) == 1 else author
        parts.append(author_clean)

    # Year
    if year:
        parts.append(f"({year})")

    # Title
    parts.append(f"'{title}'")

    # Journal / venue
    venue = ""
    if journal:
        jn = journal.strip()
        if jn.lower().startswith('arxiv'):
            venue = f"arXiv: {jn}"
        else:
            venue = jn
    if venue:
        parts.append(venue)

    # DOI
    if doi:
        parts.append(f"DOI: {doi}")

    return {
        'citation': '. '.join(parts),
        'title': title,
        'author': author,
        'year': year,
        'journal': journal,
        'doi': doi,
        'in_library': in_library,
    }


def main():
    top_n = 60
    json_output = False
    gaps_only = False

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == '--top' and i + 1 < len(args):
            top_n = int(args[i + 1])
            i += 2
        elif args[i] == '--json':
            json_output = True
            i += 1
        elif args[i] == '--gaps-only':
            gaps_only = True
            i += 1
        else:
            i += 1

    print("=" * 70)
    print("Zotero Reference Graph — Top Cited Sources")
    print("=" * 70)
    print()

    # Load
    cache = load_cache()
    library_dois = load_library_dois()

    # Aggregate references with within-paper dedup
    cite_count = Counter()
    canonical = {}

    for key, entry in cache.items():
        seen_in_paper = set()
        for ref in entry.get('references', []):
            norm_key = normalize_key(ref)
            if not norm_key or norm_key in seen_in_paper:
                continue
            seen_in_paper.add(norm_key)
            cite_count[norm_key] += 1

            title = ref.get('title', '')
            doi = ref.get('doi', '').strip().lower()
            if norm_key not in canonical or len(canonical[norm_key].get('title', '')) < len(title):
                canonical[norm_key] = {
                    'title': title,
                    'first_author': ref.get('first_author', ''),
                    'year': str(ref.get('year', '')).strip(),
                    'journal': ref.get('journal', ''),
                    'doi': doi,
                }

    # Build ranked list
    ranked = []
    for norm_key, count in cite_count.most_common(top_n * 3):
        info = canonical.get(norm_key, {})
        in_lib = bool(info.get('doi') and info['doi'] in library_dois)
        if gaps_only and in_lib:
            continue
        ranked.append({
            'count': count,
            **format_source(info, in_lib)
        })

    ranked = ranked[:top_n]

    total_unique = len(cite_count)
    n_citing = len(cache)
    n_in_lib = sum(1 for r in ranked if r['in_library'])

    if json_output:
        print(json.dumps({
            'total_unique_sources': total_unique,
            'papers_citing': n_citing,
            'top_n': top_n,
            'in_library': n_in_lib,
            'gaps': len(ranked) - n_in_lib,
            'results': ranked
        }, indent=2))
        return

    print(f"Sources cited by library:   {total_unique}")
    print(f"Papers doing the citing:    {n_citing}")
    print(f"In library (top {top_n}):         {n_in_lib}")
    print(f"Knowledge gaps (top {top_n}):    {len(ranked) - n_in_lib}")
    print()
    print("─" * 70)

    for i, r in enumerate(ranked, 1):
        tag = '📚' if r['in_library'] else '🕳️'
        print(f"\n{tag} {i:3}. [{r['count']:>3} cites]  {r['title']}")
        if r['author']:
            print(f"         {r['author']}", end='')
        if r['year']:
            print(f" ({r['year']})", end='')
        print()
        if r['journal']:
            print(f"         Venue: {r['journal']}")
        if r['doi']:
            print(f"         DOI:   {r['doi']}")

    print()
    print("─" * 70)
    print(f"📚 = in your Zotero   🕳️ = knowledge gap (not in library)")
    if gaps_only:
        print("(Showing gaps only — use without --gaps-only for full list)")
    print(f"\nFull data: {CACHE_FILE}")


if __name__ == '__main__':
    main()
