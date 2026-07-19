#!/usr/bin/env python3
"""
Zotero Reference Graph — Builder
Extracts citation links from Crossref/Semantic Scholar APIs and builds
a directed citation graph from your Zotero library.

Phase 2 of the Zotero RAG project.
"""
import sqlite3
import shutil
import sys
import json
import time
import re
import os
from pathlib import Path
from datetime import datetime
from difflib import SequenceMatcher

import requests
import networkx as nx

# --- Config ---
ZOTERO_DB = Path.home() / "Zotero" / "zotero.sqlite"
WORKSPACE = Path.home() / ".openclaw" / "workspace" / "zotero_rag"
CACHE_FILE = WORKSPACE / "citation_cache.json"
GRAPH_FILE = WORKSPACE / "citation_graph.json"
STATS_FILE = WORKSPACE / "graph_stats.json"

CROSSREF_DELAY = 0.15   # seconds between API calls (polite: ~6/sec)
SEMANTIC_SCHOLAR_DELAY = 1.0  # S2 is stricter
TITLE_MATCH_THRESHOLD = 0.85  # fuzzy title match threshold
CROSSREF_BASE = "https://api.crossref.org/works"
S2_BASE = "https://api.semantic-scholar.org/graph/v1/paper"
S2_SEARCH = "https://api.semantic-scholar.org/graph/v1/paper/search"

# --- Database helpers ---

def copy_and_open_db():
    """Copy Zotero DB to avoid locking and return connection."""
    tmp_db = Path("/tmp/zotero_graph_copy.sqlite")
    shutil.copy2(ZOTERO_DB, tmp_db)
    conn = sqlite3.connect(str(tmp_db))
    conn.row_factory = sqlite3.Row
    return conn


def get_papers(conn):
    """Extract all papers with PDFs and their metadata."""
    # Get item type IDs
    type_map = {}
    for row in conn.execute(
        "SELECT itemTypeID, typeName FROM itemTypes"
    ).fetchall():
        type_map[row["itemTypeID"]] = row["typeName"]

    # Get items with PDFs
    rows = conn.execute("""
        SELECT DISTINCT i.itemID, i.key as zotero_key
        FROM items i
        JOIN itemAttachments ia ON i.itemID = ia.parentItemID
        WHERE ia.contentType = 'application/pdf'
          AND ia.parentItemID IS NOT NULL
    """).fetchall()

    papers = {}
    for row in rows:
        item_id = row["itemID"]
        key = row["zotero_key"]
        if not key:
            continue

        # Get item type
        item_type_row = conn.execute(
            "SELECT itemTypeID FROM items WHERE itemID = ?", (item_id,)
        ).fetchone()
        item_type = type_map.get(item_type_row["itemTypeID"], "unknown") if item_type_row else "unknown"

        # Get field data
        fields = {}
        for frow in conn.execute("""
            SELECT f.fieldName, idv.value
            FROM itemData id
            JOIN fields f ON id.fieldID = f.fieldID
            JOIN itemDataValues idv ON id.valueID = idv.valueID
            WHERE id.itemID = ?
        """, (item_id,)).fetchall():
            fields[frow["fieldName"]] = frow["value"]

        # Authors
        authors = conn.execute("""
            SELECT c.firstName, c.lastName
            FROM itemCreators ic
            JOIN creators c ON ic.creatorID = c.creatorID
            WHERE ic.itemID = ?
            ORDER BY ic.orderIndex
        """, (item_id,)).fetchall()
        author_list = [
            f"{a['lastName'] or ''}, {a['firstName'] or ''}".strip(", ")
            for a in authors
        ]

        papers[key] = {
            "zotero_key": key,
            "item_id": item_id,
            "title": fields.get("title", ""),
            "date": fields.get("date", ""),
            "doi": fields.get("DOI", ""),
            "authors": author_list,
            "first_author": author_list[0] if author_list else "",
            "publication": fields.get("publicationTitle", ""),
            "item_type": item_type,
        }

    conn.close()
    return papers


# --- Normalisation ---

def normalize_title(title):
    """Normalize a title for fuzzy matching."""
    t = title.lower()
    t = re.sub(r'[^a-z0-9\s]', '', t)
    t = re.sub(r'\s+', ' ', t).strip()
    return t


def title_similarity(a, b):
    """Fuzzy title match score 0-1."""
    return SequenceMatcher(None, normalize_title(a), normalize_title(b)).ratio()


def normalize_doi(doi):
    """Normalize a DOI: lowercase, strip prefix if present."""
    if not doi:
        return ""
    d = doi.strip().lower()
    # Strip common URL prefixes
    d = re.sub(r'^https?://(dx\.)?doi\.org/', '', d)
    return d


# --- API: Crossref ---

def fetch_crossref_references(doi, session):
    """Fetch reference list for a DOI from Crossref. Returns list of reference dicts."""
    url = f"{CROSSREF_BASE}/{doi}"
    try:
        resp = session.get(url, timeout=30)
        if resp.status_code == 404:
            return None  # DOI not in Crossref
        resp.raise_for_status()
        data = resp.json()
        message = data.get("message", {})

        refs = []
        for ref in message.get("reference", []):
            ref_doi = ref.get("DOI", "")
            ref_title = ""
            # Title might be in different places depending on ref type
            if "article-title" in ref:
                ref_title = ref["article-title"]
            elif "chapter-title" in ref:
                ref_title = ref["chapter-title"]
            elif "volume-title" in ref:
                ref_title = ref["volume-title"]

            ref_authors = []
            if "author" in ref:
                for a in ref["author"]:
                    if isinstance(a, dict):
                        ref_authors.append(
                            f"{a.get('family','')}, {a.get('given','')}".strip(", ")
                        )
                    elif isinstance(a, str):
                        ref_authors.append(a)

            refs.append({
                "doi": normalize_doi(ref_doi) if ref_doi else "",
                "title": ref_title,
                "authors": ref_authors,
                "first_author": ref_authors[0] if ref_authors else "",
                "year": ref.get("year", ""),
                "journal": ref.get("journal-title", "") or ref.get("container-title", ""),
            })

        return refs

    except requests.exceptions.Timeout:
        print(f"  ⚠️  Timeout fetching Crossref data for DOI: {doi}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"  ⚠️  Error fetching Crossref data for DOI {doi}: {e}")
        return None
    except (KeyError, ValueError) as e:
        print(f"  ⚠️  Parse error for DOI {doi}: {e}")
        return None


# --- API: Semantic Scholar ---

def search_semantic_scholar(title, authors, session):
    """Search Semantic Scholar by title + author, return paper data incl references."""
    # Try title search
    query = title[:300]  # S2 has length limits
    params = {
        "query": query,
        "limit": 3,
        "fields": "title,authors,year,externalIds,citations,references"
    }
    try:
        resp = session.get(f"{S2_SEARCH}/match", params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if data.get("data") and len(data["data"]) > 0:
            return data["data"][0]  # Best match
        return None
    except Exception as e:
        print(f"  ⚠️  Semantic Scholar search error: {e}")
        return None


# --- Matching ---

def build_lookup_index(papers):
    """Build lookup indexes for fast reference matching."""
    doi_index = {}      # normalized DOI -> zotero key
    title_index = {}    # normalized title -> zotero key

    for key, paper in papers.items():
        # DOI index (most reliable)
        ndoi = normalize_doi(paper["doi"])
        if ndoi:
            doi_index[ndoi] = key

        # Title index (fallback)
        ntitle = normalize_title(paper["title"])
        if ntitle and len(ntitle) > 10:
            title_index[key] = ntitle

    return doi_index, title_index


def match_reference(ref, doi_index, title_index, papers):
    """Try to match a reference to a paper in the Zotero library."""
    # 1. Exact DOI match
    ref_doi = normalize_doi(ref.get("doi", ""))
    if ref_doi and ref_doi in doi_index:
        return doi_index[ref_doi], "doi_exact"

    # 2. Fuzzy title match
    ref_title = normalize_title(ref.get("title", ""))
    if ref_title and len(ref_title) > 15:
        best_score = 0
        best_key = None
        for key, ntitle in title_index.items():
            score = SequenceMatcher(None, ref_title, ntitle).ratio()
            if score > best_score:
                best_score = score
                best_key = key
        if best_score >= TITLE_MATCH_THRESHOLD and best_key:
            return best_key, f"title_fuzzy_{best_score:.2f}"

    # 3. First author + year match (less reliable, more false positives)
    ref_author = ref.get("first_author", "").lower()
    ref_year = str(ref.get("year", ""))
    if ref_author and ref_year:
        for key, paper in papers.items():
            pa_first = paper.get("first_author", "").lower()
            pa_year = str(paper.get("date", ""))[:4]
            if ref_author in pa_first or pa_first in ref_author:
                if ref_year == pa_year:
                    # Confirm with title check
                    rt = normalize_title(ref.get("title", ""))
                    if rt:
                        sim = SequenceMatcher(None, rt, normalize_title(paper["title"])).ratio()
                        if sim >= 0.6:
                            return key, f"author_year_title_{sim:.2f}"

    return None, None


# --- Main ---

def build_graph(force=False):
    """Main: extract citation links and build the reference graph."""
    print("=" * 60)
    print("Zotero Reference Graph — Builder (Phase 2)")
    print("=" * 60)

    # Load cache
    cache = {}
    if not force and CACHE_FILE.exists():
        with open(CACHE_FILE) as f:
            cache = json.load(f)
        print(f"📦 Loaded citation cache: {len(cache)} papers")

    # Load papers from Zotero
    print("\n📚 Reading Zotero database...")
    conn = copy_and_open_db()
    papers = get_papers(conn)
    print(f"Papers with PDFs: {len(papers)}")
    papers_with_doi = sum(1 for p in papers.values() if p["doi"])
    print(f"Papers with DOIs: {papers_with_doi} ({papers_with_doi*100//len(papers)}%)")

    # Build lookup indexes
    doi_index, title_index = build_lookup_index(papers)

    # Fetch citation data
    session = requests.Session()
    session.headers.update({
        "User-Agent": "ZoteroRAG/1.0 (mailto:annarussell1004@gmail.com)",
        "Accept": "application/json"
    })

    new_papers = 0
    papers_to_fetch = [k for k in papers if k not in cache or not cache[k].get("fetched")]
    if force:
        papers_to_fetch = list(papers.keys())

    print(f"\n🔍 Fetching citation data for {len(papers_to_fetch)} papers...")
    if len(papers_to_fetch) == 0:
        print("  All papers already cached — use --force to re-fetch")
    else:
        for i, key in enumerate(papers_to_fetch):
            paper = papers[key]
            doi = paper.get("doi", "")
            title = paper.get("title", "")

            if doi:
                time.sleep(CROSSREF_DELAY)
                refs = fetch_crossref_references(doi, session)
                if refs is not None:
                    cache[key] = {
                        "fetched": True,
                        "source": "crossref",
                        "doi": doi,
                        "title": title,
                        "reference_count": len(refs),
                        "references": refs
                    }
                    new_papers += 1
                else:
                    # Crossref didn't have it, try Semantic Scholar
                    print(f"  Crossref miss for {key}, trying Semantic Scholar...")
                    time.sleep(SEMANTIC_SCHOLAR_DELAY)
                    s2_data = search_semantic_scholar(title, paper.get("authors", []), session)
                    if s2_data:
                        s2_refs = s2_data.get("references", [])
                        cache[key] = {
                            "fetched": True,
                            "source": "semantic_scholar",
                            "s2_id": s2_data.get("paperId", ""),
                            "title": title,
                            "reference_count": len(s2_refs),
                            "references": [
                                {
                                    "doi": r.get("externalIds", {}).get("DOI", ""),
                                    "title": r.get("title", ""),
                                    "authors": [a.get("name", "") for a in r.get("authors", [])],
                                    "first_author": (r.get("authors", [{}])[0].get("name", "") if r.get("authors") else ""),
                                    "year": str(r.get("year", "")),
                                }
                                for r in s2_refs
                            ]
                        }
                        new_papers += 1
                    else:
                        cache[key] = {"fetched": True, "source": "none", "reference_count": 0, "references": []}

            else:
                # No DOI — try Semantic Scholar by title
                time.sleep(SEMANTIC_SCHOLAR_DELAY)
                s2_data = search_semantic_scholar(title, paper.get("authors", []), session)
                if s2_data:
                    s2_refs = s2_data.get("references", [])
                    cache[key] = {
                        "fetched": True,
                        "source": "semantic_scholar",
                        "s2_id": s2_data.get("paperId", ""),
                        "title": title,
                        "reference_count": len(s2_refs),
                        "references": [
                            {
                                "doi": r.get("externalIds", {}).get("DOI", ""),
                                "title": r.get("title", ""),
                                "authors": [a.get("name", "") for a in r.get("authors", [])],
                                "first_author": (r.get("authors", [{}])[0].get("name", "") if r.get("authors") else ""),
                                "year": str(r.get("year", "")),
                            }
                            for r in s2_refs
                        ]
                    }
                    new_papers += 1
                else:
                    cache[key] = {"fetched": True, "source": "none", "reference_count": 0, "references": []}

            if (i + 1) % 50 == 0:
                print(f"  Progress: {i+1}/{len(papers_to_fetch)}")

        print(f"Fetched citation data for {new_papers} new papers")

    # Save cache
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=2)
    print(f"💾 Cache saved: {CACHE_FILE}")

    # Match references to Zotero items
    print("\n🔗 Matching references to Zotero items...")
    graph = {}  # zotero_key -> list of cited zotero_keys (with metadata)
    matched_count = 0
    unmatched_count = 0
    match_methods = {}

    for key, entry in cache.items():
        refs = entry.get("references", [])
        cited_keys = []
        for ref in refs:
            matched_key, method = match_reference(ref, doi_index, title_index, papers)
            if matched_key and matched_key != key:  # don't self-cite
                cited_keys.append(matched_key)
                matched_count += 1
                match_methods[method] = match_methods.get(method, 0) + 1
            else:
                unmatched_count += 1

        if cited_keys:
            graph[key] = list(set(cited_keys))  # deduplicate

    print(f"References matched to library: {matched_count}")
    print(f"References unmatched (not in library): {unmatched_count}")
    print(f"Papers with ≥1 matched citation: {len(graph)}")
    print(f"Match methods: {json.dumps(match_methods, indent=2)}")

    # Build NetworkX graph for analysis
    print("\n📊 Building NetworkX graph...")
    G = nx.DiGraph()

    # Add all papers as nodes
    for key, paper in papers.items():
        G.add_node(key, **paper)

    # Add citation edges
    for src_key, cited_keys in graph.items():
        for tgt_key in cited_keys:
            if tgt_key in papers:  # sanity check
                G.add_edge(src_key, tgt_key)

    # Compute statistics
    print("\n📈 Computing graph statistics...")
    stats = {
        "generated": datetime.now().isoformat(),
        "total_papers": len(papers),
        "papers_with_edges": len(graph),
        "total_edges": G.number_of_edges(),
        "total_citations_matched": matched_count,
        "total_citations_unmatched": unmatched_count,
        "match_methods": match_methods,
        "density": round(nx.density(G), 6),
    }

    # Most cited papers (in-degree)
    in_degree = dict(G.in_degree())
    top_cited = sorted(
        [(key, deg) for key, deg in in_degree.items() if deg > 0],
        key=lambda x: x[1], reverse=True
    )[:25]

    stats["most_cited"] = [
        {
            "zotero_key": key,
            "citations": deg,
            "title": papers[key]["title"] if key in papers else "?",
            "authors": papers[key].get("first_author", "") if key in papers else "",
            "date": papers[key].get("date", "") if key in papers else "",
        }
        for key, deg in top_cited
    ]

    # Papers with most outgoing citations (bibliographies)
    out_degree = dict(G.out_degree())
    top_citers = sorted(
        [(key, deg) for key, deg in out_degree.items() if deg > 0],
        key=lambda x: x[1], reverse=True
    )[:25]

    stats["most_citing"] = [
        {
            "zotero_key": key,
            "cites": deg,
            "title": papers[key]["title"] if key in papers else "?",
            "authors": papers[key].get("first_author", "") if key in papers else "",
            "date": papers[key].get("date", "") if key in papers else "",
        }
        for key, deg in top_citers
    ]

    # Orphan papers (not cited by anything in the library, and cite nothing matched)
    orphans = [key for key in papers if G.in_degree(key) == 0 and G.out_degree(key) == 0]
    stats["orphan_papers"] = len(orphans)
    stats["orphan_pct"] = round(len(orphans) * 100 / len(papers), 1)

    # Connected components (weak)
    wcc = list(nx.weakly_connected_components(G))
    stats["weakly_connected_components"] = len(wcc)
    stats["largest_component_size"] = max(len(c) for c in wcc)
    stats["largest_component_pct"] = round(stats["largest_component_size"] * 100 / len(papers), 1)

    # Citation clusters (Louvain communities on undirected version)
    try:
        import community as community_louvain
        UG = G.to_undirected()
        partition = community_louvain.best_partition(UG)
        num_communities = len(set(partition.values()))
        stats["louvain_communities"] = num_communities
        # Papers per community (top 5)
        comm_sizes = {}
        for node, comm in partition.items():
            comm_sizes[comm] = comm_sizes.get(comm, 0) + 1
        top_comms = sorted(comm_sizes.items(), key=lambda x: x[1], reverse=True)[:5]
        stats["top_communities"] = [
            {"community": c, "size": s,
             "sample_titles": [
                 papers[n]["title"][:80]
                 for n in G.nodes()
                 if partition.get(n) == c
             ][:3]}
            for c, s in top_comms
        ]
    except ImportError:
        stats["louvain_communities"] = "python-louvain not installed"

    # Save outputs
    # 1. Save graph as adjacency list (lightweight JSON)
    graph_output = {key: list(cited) for key, cited in graph.items()}
    with open(GRAPH_FILE, "w") as f:
        json.dump(graph_output, f, indent=2)
    print(f"💾 Graph saved: {GRAPH_FILE} ({len(graph_output)} papers, {sum(len(v) for v in graph_output.values())} edges)")

    # 2. Save stats
    with open(STATS_FILE, "w") as f:
        json.dump(stats, f, indent=2)
    print(f"💾 Stats saved: {STATS_FILE}")

    # Print summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Papers in library:        {stats['total_papers']}")
    print(f"Papers with citations:    {stats['papers_with_edges']}")
    print(f"Citation edges (matched): {stats['total_edges']}")
    print(f"Orphan papers:            {stats['orphan_papers']} ({stats['orphan_pct']}%)")
    print(f"Largest component:        {stats['largest_component_size']} papers ({stats['largest_component_pct']}%)")
    print(f"Louvain communities:      {stats.get('louvain_communities', 'N/A')}")
    print(f"\n🏆 Most cited papers (top 10):")
    for i, p in enumerate(stats["most_cited"][:10], 1):
        title = p["title"][:70]
        print(f"  {i:2}. [{p['citations']} cites] {title} — {p['authors']} ({p['date']})")

    print("\n✅ Reference graph build complete!")


if __name__ == "__main__":
    force = "--force" in sys.argv
    build_graph(force=force)
