# Claude Webtools Integration (Optional)

Scrinium is agent-first: users talk to an agent, and the agent orchestrates local Scrinium skills.  
If you also want live web search/extraction, you can integrate [AnterCreeper/claude-webtools](https://github.com/AnterCreeper/claude-webtools) as an external capability layer.

## When to use this

- You need **internet discovery** (news, latest announcements, online docs) in addition to the local paper KB.
- You want the agent to combine:
  - Scrinium local retrieval (`/scrinium:search`, `/scrinium:show`, etc.)
  - external web lookup from claude-webtools.

## Recommended setup

1. Install and configure `claude-webtools` by following its README.
2. Keep Scrinium as the authoritative local knowledge pipeline (ingest/index/enrich).
3. In agent workflows:
   - use Scrinium first for reproducible local evidence;
   - use webtools only when freshness or external coverage is required.

## Operational guidelines

- Prefer local KB evidence for stable academic claims.
- For time-sensitive facts, cross-check via webtools and record access date.
- When webtools is unavailable, agent should degrade gracefully to local-only Scrinium workflows.
