#!/usr/bin/env python3
"""
Zotero RAG — Build Index
Extracts text from Zotero PDFs, chunks, embeds, and indexes in ChromaDB.
"""
import sqlite3
import shutil
import sys
import json
import os
import re
from pathlib import Path
from datetime import datetime

# --- Config ---
ZOTERO_DB = Path.home() / "Zotero" / "zotero.sqlite"
ZOTERO_STORAGE = Path.home() / "Zotero" / "storage"
WORKSPACE = Path.home() / ".openclaw" / "workspace" / "zotero_rag"
CHROMA_PATH = WORKSPACE / "chroma_db"
STATE_FILE = WORKSPACE / "index_state.json"
CHUNK_SIZE = 1000  # characters per chunk
CHUNK_OVERLAP = 200

# Collections to index (empty = all with PDFs)
TARGET_COLLECTIONS = []  # Leave empty for all, or specify names

# --- Field IDs from Zotero schema ---
FIELD_TITLE = 1
FIELD_ABSTRACT = 2
FIELD_DATE = 6
FIELD_URL = 13
FIELD_VOLUME = 19
FIELD_PAGES = 32
FIELD_PUBLICATION = 38
FIELD_DOI = 59
FIELD_ISSUE = 76


def get_zotero_data(db_path):
    """Extract all items with PDFs and their metadata from Zotero DB."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    
    # Get item IDs that have PDF attachments (by parentItemID)
    pdf_parents = set()
    pdf_paths = {}  # parentItemID -> (attachment_key, filename)
    rows = conn.execute("""
        SELECT ia.parentItemID, ai.key as attKey, ia.path
        FROM itemAttachments ia
        JOIN items ai ON ia.itemID = ai.itemID
        WHERE ia.contentType = 'application/pdf'
          AND ia.parentItemID IS NOT NULL
    """).fetchall()
    for row in rows:
        pdf_parents.add(row["parentItemID"])
        # path is like "storage:filename.pdf"
        filename = row["path"].replace("storage:", "") if row["path"] else None
        pdf_paths[row["parentItemID"]] = (row["attKey"], filename)
    
    print(f"Found {len(pdf_parents)} items with PDF attachments")
    
    # Get items that are in target collections (or all if none specified)
    if TARGET_COLLECTIONS:
        placeholders = ",".join("?" * len(TARGET_COLLECTIONS))
        collection_rows = conn.execute(f"""
            SELECT DISTINCT ci.itemID, c.collectionName
            FROM collectionItems ci
            JOIN collections c ON ci.collectionID = c.collectionID
            WHERE c.collectionName IN ({placeholders})
        """, TARGET_COLLECTIONS).fetchall()
        target_items = {row["itemID"]: row["collectionName"] for row in collection_rows}
        print(f"Target collections: {TARGET_COLLECTIONS} -> {len(target_items)} items")
    else:
        # All items with PDFs, collection name = first collection they belong to
        collection_rows = conn.execute("""
            SELECT ci.itemID, c.collectionName
            FROM collectionItems ci
            JOIN collections c ON ci.collectionID = c.collectionID
            ORDER BY ci.itemID, ci.orderIndex
        """).fetchall()
        target_items = {}
        for row in collection_rows:
            if row["itemID"] not in target_items:
                target_items[row["itemID"]] = row["collectionName"]
    
    # Filter to items with PDFs
    eligible = {iid for iid in target_items if iid in pdf_parents}
    print(f"Items with PDFs in target collections: {len(eligible)}")
    
    # Get metadata for eligible items
    papers = []
    for item_id in eligible:
        # Authors
        authors = conn.execute("""
            SELECT c.firstName, c.lastName, ct.creatorType
            FROM itemCreators ic
            JOIN creators c ON ic.creatorID = c.creatorID
            JOIN creatorTypes ct ON ic.creatorTypeID = ct.creatorTypeID
            WHERE ic.itemID = ?
            ORDER BY ic.orderIndex
        """, (item_id,)).fetchall()
        author_str = "; ".join(
            f"{a['firstName'] or ''} {a['lastName'] or ''}".strip()
            for a in authors
        )
        
        # Get item key
        item_key_row = conn.execute(
            "SELECT key FROM items WHERE itemID = ?", (item_id,)
        ).fetchone()
        item_key = item_key_row["key"] if item_key_row else None
        
        # Field data
        fields = {}
        for row in conn.execute("""
            SELECT f.fieldName, idv.value
            FROM itemData id
            JOIN fields f ON id.fieldID = f.fieldID
            JOIN itemDataValues idv ON id.valueID = idv.valueID
            WHERE id.itemID = ?
        """, (item_id,)).fetchall():
            fields[row["fieldName"]] = row["value"]
        
        att_key, filename = pdf_paths.get(item_id, (None, None))
        pdf_path = ZOTERO_STORAGE / att_key / filename if att_key and filename else None
        
        paper = {
            "item_id": item_id,
            "key": item_key,
            "title": fields.get("title", "Untitled"),
            "date": fields.get("date", ""),
            "abstract": fields.get("abstractNote", ""),
            "publication": fields.get("publicationTitle", ""),
            "doi": fields.get("DOI", ""),
            "url": fields.get("url", ""),
            "volume": fields.get("volume", ""),
            "issue": fields.get("issue", ""),
            "pages": fields.get("pages", ""),
            "authors": author_str,
            "collection": target_items.get(item_id, ""),
            "attachment_key": att_key,
            "filename": filename,
            "pdf_path": str(pdf_path) if pdf_path else None,
        }
        papers.append(paper)
    
    conn.close()
    return papers


def extract_text(pdf_path):
    """Extract text from a PDF using pymupdf."""
    try:
        import pymupdf
        doc = pymupdf.open(pdf_path)
        text = ""
        for page in doc:
            text += page.get_text() + "\n"
        doc.close()
        return text.strip()
    except Exception as e:
        print(f"  ERROR extracting {pdf_path}: {e}")
        return ""


def clean_text(text):
    """Clean extracted text: normalize whitespace, remove junk."""
    # Collapse multiple newlines
    text = re.sub(r'\n{3,}', '\n\n', text)
    # Remove lines that are just numbers (page numbers)
    text = re.sub(r'^\d+\s*$', '', text, flags=re.MULTILINE)
    # Normalize whitespace
    text = re.sub(r'[ \t]+', ' ', text)
    return text.strip()


def chunk_text(text, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    """Split text into overlapping chunks, trying to break on paragraph/sentence boundaries."""
    paragraphs = text.split('\n\n')
    chunks = []
    current_chunk = ""
    
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        
        # If this paragraph alone is bigger than chunk_size, split on sentences
        if len(para) > chunk_size:
            sentences = re.split(r'(?<=[.!?])\s+', para)
            for sent in sentences:
                if len(current_chunk) + len(sent) + 1 <= chunk_size:
                    current_chunk += " " + sent if current_chunk else sent
                else:
                    if current_chunk:
                        chunks.append(current_chunk.strip())
                    # Start new chunk with overlap from previous
                    if chunks:
                        overlap_text = chunks[-1][-overlap:] if len(chunks[-1]) > overlap else chunks[-1]
                        current_chunk = overlap_text + " " + sent
                    else:
                        current_chunk = sent
        else:
            if len(current_chunk) + len(para) + 2 <= chunk_size:
                current_chunk += "\n\n" + para if current_chunk else para
            else:
                chunks.append(current_chunk.strip())
                # Overlap: keep last bit of previous chunk
                if chunks:
                    overlap_text = chunks[-1][-overlap:] if len(chunks[-1]) > overlap else chunks[-1]
                    current_chunk = overlap_text + "\n\n" + para
                else:
                    current_chunk = para
    
    if current_chunk.strip():
        chunks.append(current_chunk.strip())
    
    return chunks


def load_state():
    """Load index state (previously indexed paper keys)."""
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"indexed_keys": [], "last_build": None}


def save_state(indexed_keys):
    """Save index state."""
    with open(STATE_FILE, "w") as f:
        json.dump({
            "indexed_keys": indexed_keys,
            "last_build": datetime.now().isoformat(),
            "paper_count": len(indexed_keys)
        }, f, indent=2)


def build_index(force=False):
    """Main: extract, chunk, embed, index."""
    print("=" * 60)
    print("Zotero RAG — Build Index")
    print("=" * 60)
    
    # Copy DB to avoid locking issues
    tmp_db = Path("/tmp/zotero_rag_copy.sqlite")
    shutil.copy2(ZOTERO_DB, tmp_db)
    
    # Get paper metadata
    print("\n📚 Reading Zotero database...")
    papers = get_zotero_data(tmp_db)
    print(f"Total papers with PDFs: {len(papers)}")
    
    # Load state for incremental updates
    state = load_state()
    indexed_keys = set(state["indexed_keys"])
    
    # Filter to new/changed papers (or all if force)
    if force:
        to_index = papers
        print("Force rebuild: indexing all papers")
    else:
        to_index = [p for p in papers if p["key"] not in indexed_keys]
        print(f"New papers to index: {len(to_index)} (already indexed: {len(indexed_keys)})")
    
    if not to_index:
        print("Nothing new to index!")
        return
    
    # Extract text from PDFs
    print(f"\n📄 Extracting text from {len(to_index)} PDFs...")
    texts = {}
    failed = 0
    for i, paper in enumerate(to_index):
        if paper["pdf_path"] and os.path.exists(paper["pdf_path"]):
            raw_text = extract_text(paper["pdf_path"])
            if raw_text:
                texts[paper["key"]] = clean_text(raw_text)
                if (i + 1) % 50 == 0:
                    print(f"  Extracted {i+1}/{len(to_index)}...")
            else:
                failed += 1
        else:
            failed += 1
    
    print(f"Extracted: {len(texts)} papers ({failed} failed)")
    
    # Chunk texts
    print(f"\n✂️  Chunking texts...")
    all_chunks = []
    all_metadata = []
    total_chunks = 0
    for paper in to_index:
        if paper["key"] not in texts:
            continue
        chunks = chunk_text(texts[paper["key"]])
        for ci, chunk in enumerate(chunks):
            all_chunks.append(chunk)
            all_metadata.append({
                "zotero_key": paper["key"],
                "title": paper["title"],
                "authors": paper["authors"],
                "date": paper["date"],
                "publication": paper["publication"],
                "doi": paper["doi"],
                "abstract": paper["abstract"][:500] if paper["abstract"] else "",
                "collection": paper["collection"],
                "chunk_index": ci,
                "total_chunks": len(chunks),
                "source": f"{paper['title']} ({paper['date']}) - chunk {ci+1}/{len(chunks)}"
            })
        total_chunks += len(chunks)
    
    print(f"Total chunks: {total_chunks} from {len(texts)} papers")
    
    # Generate embeddings and index
    print(f"\n🧠 Generating embeddings (this will take a while for {total_chunks} chunks)...")
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer("all-MiniLM-L6-v2")
    
    print("  Encoding chunks...")
    embeddings = model.encode(all_chunks, show_progress_bar=True, batch_size=32)
    
    # Store in ChromaDB
    print(f"\n💾 Storing in ChromaDB...")
    import chromadb
    from chromadb.config import Settings
    
    client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    
    # Get or create collection
    try:
        collection = client.get_collection("zotero_papers")
        print("  Using existing collection")
    except Exception:
        collection = client.create_collection(
            "zotero_papers",
            metadata={"description": "Zotero library papers with full-text search"}
        )
        print("  Created new collection")
    
    # Add in batches
    BATCH_SIZE = 100
    for i in range(0, len(all_chunks), BATCH_SIZE):
        batch_end = min(i + BATCH_SIZE, len(all_chunks))
        batch_ids = [f"{all_metadata[j]['zotero_key']}_chunk{all_metadata[j]['chunk_index']}" 
                     for j in range(i, batch_end)]
        collection.add(
            ids=batch_ids,
            embeddings=embeddings[i:batch_end].tolist(),
            documents=all_chunks[i:batch_end],
            metadatas=all_metadata[i:batch_end],
        )
        print(f"  Batch {i//BATCH_SIZE + 1}: indexed {i}–{batch_end-1}")
    
    # Update state
    new_indexed = indexed_keys | {p["key"] for p in to_index if p["key"] in texts}
    save_state(list(new_indexed))
    
    print(f"\n✅ Index complete!")
    print(f"   Papers in index: {len(new_indexed)}")
    print(f"   Total chunks: {total_chunks}")
    print(f"   ChromaDB: {CHROMA_PATH}")


if __name__ == "__main__":
    force = "--force" in sys.argv
    build_index(force=force)
