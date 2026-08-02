# Insights Guide

`scrinium insights` summarizes recent search and reading behavior from `data/metrics.db`.

## Usage

```bash
scrinium insights
scrinium insights --days 7
scrinium insights --days 30
```

## Output Sections

1. Search hot keywords extracted from recent search queries
2. Most-read papers aggregated by resolved title
3. Weekly read trend shown as an ASCII bar chart
4. Semantically adjacent unread-paper recommendations based on recent reading
5. Active workspaces with paper counts

## Preconditions

- Metrics data must already exist in `data/metrics.db`
- Search commands and `show` accumulate the events used here
- Neighbor recommendations require vector search to be available; otherwise the command degrades gracefully
