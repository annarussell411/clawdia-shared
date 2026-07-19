# Zotero RAG

**Semantic search and citation graph analysis over a personal Zotero research library.**

Built for systematic literature review workflows. Indexes your PDFs, lets you ask natural-language questions of your literature, and builds a citation network from Crossref and Semantic Scholar to surface influential sources, knowledge gaps, and thematic clusters.

---

## Overview

The toolkit has two independent components:

### Phase 1 — Semantic Search (RAG)

A retrieval-augmented generation pipeline over your Zotero PDF library.

- Extracts full text from all PDFs in your Zotero storage
- Chunks documents into overlapping 500-word segments
- Embeds chunks using `all-MiniLM-L6-v2` (SentenceTransformers)
- Stores embeddings in ChromaDB for fast cosine-similarity retrieval
- Supports natural-language queries: ask a question, get the most relevant passages ranked by semantic similarity, grouped by paper

**Use it to:** explore your literature conceptually, find relevant papers by idea rather than keyword, surface unexpected connections, and ground your writing in the actual contents of your library.

### Phase 2 — Reference Graph Analysis

A citation network builder that reveals the structure of your literature.

- Fetches reference lists for each paper via Crossref (DOI) and Semantic Scholar (title matching)
- Fuzzy-matches references against your Zotero library to identify which of your papers cite which others
- Detects knowledge gaps: foundational works that are cited heavily *by* your literature but are not in your library
- Computes network statistics: most-cited papers, citation density, largest connected component, Louvain community detection
- Outputs structured JSON (graph, stats, cache) and human-readable summaries

**Use it to:** identify the most influential papers in your corpus, find what you're missing, understand the thematic structure of your field, and justify the scope and positioning of your review.

---

## Repository Structure

```
zotero_rag/
├── build_index.py       # Phase 1: extract PDFs → Chunk → Embed → ChromaDB
├── query.py             # Phase 1: semantic search over indexed papers
├── build_graph.py       # Phase 2: fetch references → match → build citation graph
├── top_cited_sources.py # Phase 2: analyse most-cited sources + gap detection
├── index_state.json     # (generated) incremental indexing state
├── chroma_db/           # (generated) vector embeddings database
├── citation_cache.json  # (generated) cached reference data from APIs
├── citation_graph.json  # (generated) matched citation edges
├── graph_stats.json     # (generated) network statistics
├── Suggested_Additions.md  # (generated) curated knowledge gap report
└── README.md
```

---

## Requirements

- **Python 3.10+** with:
  - `sentence-transformers` — embedding model
  - `chromadb` — vector database
  - `pymupdf` (fitz) — PDF text extraction
  - `networkx` + `python-louvain` — graph analysis
  - `requests` — API calls to Crossref and Semantic Scholar
- **Zotero** installed with PDFs stored locally (`~/Zotero/storage/`)
- ~90 MB disk for embeddings (400 papers ≈ 15,000 chunks)
- Internet access for Phase 2 (API calls, rate-limited)

Install dependencies:

```bash
pip install sentence-transformers chromadb pymupdf networkx python-louvain requests
```

---

## Usage

### Phase 1 — Build the index (first run)

```bash
python3 build_index.py
```

Extracts text from all PDFs, chunks, embeds, and stores in ChromaDB. Incremental on subsequent runs — only processes new or modified papers.

**Time:** ~5 minutes for 400 papers on Apple Silicon.

### Phase 1 — Query your literature

```bash
python3 query.py "what are the key dimensions of agentic AI alignment?"
```

Returns the top 10 most semantically relevant passages, grouped by paper, with authors, year, DOI, and context snippets.

### Phase 2 — Build the citation graph

```bash
python3 build_graph.py
```

Fetches reference lists for each paper (Crossref first, Semantic Scholar fallback), fuzzy-matches them against your library, and builds a directed citation graph. Caches results — subsequent runs are incremental.

**Time:** ~10–15 minutes for 400 papers (rate-limited API calls).

Force a full rebuild:

```bash
python3 build_graph.py --force
```

### Phase 2 — Analyse most-cited sources

```bash
python3 top_cited_sources.py             # Top 60 most-cited sources
python3 top_cited_sources.py --top 20    # Custom count
python3 top_cited_sources.py --gaps-only # Knowledge gaps only (sources you don't own)
python3 top_cited_sources.py --json      # Machine-readable output
```

Displays a ranked list with:
- 📚 = in your Zotero library
- 🕳️ = knowledge gap (cited by your literature, but you don't have it)

---

## How It Works

### Phase 1: Semantic Search Pipeline

```
Zotero PDFs  →  PyMuPDF text extraction  →  500-word sliding-window chunks
                                                    ↓
                                          SentenceTransformer embeddings
                                                    ↓
                                               ChromaDB vector store
                                                    ↓
Query: "How do sociotechnical systems..."  →  Embed query  →  cosine similarity  →  top-k chunks
```

The incremental indexer (`build_index.py`) tracks file modification times. Only new or changed PDFs are reprocessed. Removed papers are cleaned from ChromaDB automatically.

### Phase 2: Citation Graph Pipeline

```
Zotero SQLite  →  Extract DOIs, titles, authors
                          ↓
            Crossref API (DOI lookup) OR Semantic Scholar (title search)
                          ↓
              Fetch reference lists for each paper
                          ↓
         Fuzzy-match references against library DOIs and titles
              ├── DOI exact match → immediate resolution
              └── Title similarity ≥ 0.85 → matched
                          ↓
            Build NetworkX directed graph (A cites B)
                          ↓
         Compute: in-degree ranking, density, connected components, Louvain communities
                          ↓
         Output: graph_stats.json, citation_graph.json, Suggested_Additions.md
```

**Matching strategy:** references are matched against your library using DOI exact match first (reliable), then fuzzy title matching with a similarity threshold of 0.85 (catches minor formatting differences). Unmatched references are still tracked for gap analysis — a highly-cited unmatched source is flagged as a potential knowledge gap.

### Why Two Phases?

The phases are deliberately independent. Semantic search answers *"what does my literature say about X?"* — it's introspective, working within your corpus. The citation graph answers *"where does my literature sit in the broader field, and what am I missing?"* — it's relational, connecting your corpus to the wider literature through citation patterns.

Together they support a systematic review workflow: use semantic search to map your conceptual landscape, then use the citation graph to validate coverage, identify gaps, and understand influence.

---

## Current State

| Metric | Value |
|--------|-------|
| Papers indexed | 404 |
| Citation edges matched | 134 |
| Unique external sources cited | ~9,000 |
| Orphan papers (no citations in/out) | 76% |
| Largest connected component | 22% of papers |
| Louvain communities | 318 |

The high orphan rate is expected for a broad scoping review — it reflects the diversity of sources being surveyed rather than a weakness in the matching.

---

## Research Application

This toolkit was built to support a systematic review of **multi-agent alignment** — the intersection of multi-agent systems, AI safety, and sociotechnical design.

It has been used to:
- Discover that the most-cited works within this corpus cluster around sociotechnical systems theory (Trist, Baxter, Pasmore) and agentic AI surveys (Wang, Acharya, Sapkota)
- Identify critical knowledge gaps including generative agents (Park et al. 2023), AI control frameworks (Greenblatt et al. 2023), and constitutional AI (Bai et al. 2022)
- Surface thematic communities via Louvain clustering: sociotechnical design, neural architectures, LLM safety, and AI alignment
- Generate a prioritised reading list from the 9,000+ unique external references

---

## Limitations

- **Phase 1** uses a lightweight embedding model (`all-MiniLM-L6-v2`). Adequate for conceptual search; for specialised domains, a larger model (e.g., `allenai/specter2`) would improve precision on technical terminology.
- **Phase 2** relies on Crossref and Semantic Scholar APIs. Coverage is excellent for journal articles and conference proceedings but spotty for books, book chapters, and preprints. Approximately 90% of fetched references go unmatched — this is primarily due to books and non-DOI items that cannot be resolved against a DOI-indexed library.
- **Incremental only** within each phase: adding papers requires re-running `build_index.py` (fast) and `build_graph.py` (API-bound). There is no unified rebuild command.
- **No persistent web interface** — all interaction is CLI-based, designed for use by an AI assistant or researcher comfortable with the terminal.

---

## Citation

If you use this toolkit in your research, please cite:

> Russell, A. (2026). Zotero RAG: Semantic search and citation graph analysis for systematic literature review. https://github.com/[repo-url]

---

*Built for the multi-agent alignment systematic review. Questions, suggestions, and contributions welcome.*
