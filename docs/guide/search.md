# Search & Browse

Scrinium provides multiple search modes to find papers in your knowledge base.

## Search Modes

### Keyword Search (FTS5)

```bash
scrinium search "turbulent boundary layer"
```

Searches title, abstract, and conclusion using SQLite FTS5 full-text search.

### Semantic Search

```bash
scrinium vsearch "methods for predicting flow separation"
```

Uses Qwen3 embeddings + FAISS for meaning-based retrieval.

### Unified Search (Fusion)

```bash
scrinium usearch "Reynolds stress modeling"
```

Combines keyword and semantic results using Reciprocal Rank Fusion (RRF).

### Federated Search

```bash
scrinium fsearch "wall turbulence" --scope main,proceedings,explore:*,arxiv
```

Searches across the main library, proceedings, one or more `explore` silos, and arXiv in one command.

### Author Search

```bash
scrinium search-author "Smith"
```

## Viewing Papers

Load paper content at different detail levels:

```bash
scrinium show <paper-id> --layer 1  # metadata
scrinium show <paper-id> --layer 2  # + abstract
scrinium show <paper-id> --layer 3  # + conclusion
scrinium show <paper-id> --layer 4  # full text
```

## Filtering

All search commands support filters:

```bash
scrinium search "turbulence" --year 2020-2024 --journal "JFM" --type review
```

## Top-Cited Papers

```bash
scrinium top-cited --top 20 --year 2020-
```

## arXiv Search and Fetch

```bash
scrinium arxiv search "compliant wall turbulence" --category physics.flu-dyn
scrinium arxiv fetch 2604.00484 --ingest
```

Use `arxiv search` to discover preprints and `arxiv fetch` to download a PDF or send it directly into the ingest pipeline.

## Scientific Tool Documentation

```bash
scrinium toolref search openfoam "y plus"
scrinium toolref show qe pw conv_thr
```

Use `toolref` when you need authoritative parameter or command documentation for supported scientific tools.
