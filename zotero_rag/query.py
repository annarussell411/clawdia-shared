#!/usr/bin/env python3
"""
Zotero RAG — Query
Takes a question, searches the ChromaDB index, returns relevant chunks with metadata.
Usage: python3 query.py "your question here" [--top-k 10] [--full-text]
"""
import sys
import json
from pathlib import Path

WORKSPACE = Path.home() / ".openclaw" / "workspace" / "zotero_rag"
CHROMA_PATH = WORKSPACE / "chroma_db"


def query(question, top_k=10, full_text=False):
    """Search the index and return relevant chunks."""
    from sentence_transformers import SentenceTransformer
    import chromadb
    
    if not CHROMA_PATH.exists():
        print(json.dumps({"error": "Index not built yet. Run build_index.py first."}))
        return
    
    # Load model and DB
    model = SentenceTransformer("all-MiniLM-L6-v2")
    client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    
    try:
        collection = client.get_collection("zotero_papers")
    except Exception:
        print(json.dumps({"error": "Collection 'zotero_papers' not found. Run build_index.py first."}))
        return
    
    # Embed and search
    query_embedding = model.encode([question])[0]
    results = collection.query(
        query_embeddings=[query_embedding.tolist()],
        n_results=top_k,
        include=["documents", "metadatas", "distances"]
    )
    
    # Format results
    output = {
        "question": question,
        "top_k": top_k,
        "results": []
    }
    
    for i, (doc, meta, dist) in enumerate(zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0]
    )):
        similarity = 1 - dist  # ChromaDB uses cosine distance; convert to similarity
        result = {
            "rank": i + 1,
            "score": round(similarity, 4),
            "title": meta.get("title", ""),
            "authors": meta.get("authors", ""),
            "date": meta.get("date", ""),
            "publication": meta.get("publication", ""),
            "doi": meta.get("doi", ""),
            "collection": meta.get("collection", ""),
            "chunk_index": meta.get("chunk_index", 0),
            "total_chunks": meta.get("total_chunks", 0),
        }
        if full_text:
            result["text"] = doc
        else:
            result["text_preview"] = doc[:300] + "..." if len(doc) > 300 else doc
        output["results"].append(result)
    
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 query.py 'your question' [--top-k N] [--full-text]")
        sys.exit(1)
    
    question = sys.argv[1]
    top_k = 10
    full_text = False
    
    args = sys.argv[2:]
    for i, arg in enumerate(args):
        if arg == "--top-k" and i + 1 < len(args):
            top_k = int(args[i + 1])
        if arg == "--full-text":
            full_text = True
    
    query(question, top_k=top_k, full_text=full_text)
