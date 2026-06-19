# Clawdia Scripts

## zotero_summarise.py

Reads papers in a Zotero collection, generates a 4-sentence triage summary 
via Clawdia, posts the summary as a child note in Zotero, and applies 
triage and category tags.

### Setup
1. Enable Zotero local API: Settings → Advanced → Allow other applications
2. Install deps: `pip install pypdf requests`
3. Make executable: `chmod +x zotero_summarise.py`

### Usage
```bash
# List collections to find the right one
./zotero_summarise.py --list-collections

# Apply colour scheme (one-time)
./zotero_summarise.py --setup-colours

# Dry run on a collection (no Zotero writes)
./zotero_summarise.py "collection-name" --dry-run

# Process the collection for real
./zotero_summarise.py "collection-name"
```

### Safety
- Never modifies existing notes
- Never removes existing tags  
- Skips papers already tagged 'summarised'
- --setup-colours REPLACES the tag colour scheme (run once)cd 

### Triage criteria
- 🔴-core: Directly addresses value alignment in multi-agent sociotechnical systems
- 🟡-context: Theoretical or methodological support  
- 🟢-background: General context
- ⚫-drop: Low quality or covered better elsewhere

### Reading progression (manual tags)
- skimmed: Anna has done Stage 1 scan herself
- READ: Anna has done comprehensive read with detailed notes
- deep-read: Anna has done critical engagement, reconstructed arguments