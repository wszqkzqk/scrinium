# Academic Writing

Scrinium includes several agent skills to assist with academic writing. These work best through an agent host that can load Scrinium skills; the examples below use Claude Code-style slash-skill names.

## Available Writing Skills

### Literature Review (`/literature-review`)

Generates a structured literature review from papers in a workspace. Organizes by topic, builds narrative, identifies gaps, and exports BibTeX.

### Paper Writing (`/paper-writing`)

Assists with drafting specific paper sections: Introduction, Related Work, Method, Results, Discussion, Conclusion. Uses workspace papers for citations.

### Writing Polish (`/writing-polish`)

Polishes academic prose — removes AI-generated patterns, improves clarity, adapts to a target journal style. Supports English and Chinese.

### Review Response (`/review-response`)

Drafts point-by-point responses to peer reviewer comments, locating evidence from workspace papers and the manuscript.

### Research Gap (`/research-gap`)

Identifies unexplored areas and open questions by analyzing literature in a workspace through topic clustering, citation analysis, and cross-paper comparison.

### Citation Check (`/citation-check`)

Verifies citations in AI-generated or human-written text against the knowledge base. Catches hallucinated references and wrong metadata.

## Workflow

1. Create a workspace: use `/workspace` to organize relevant papers
2. Use the writing skill from your agent host, for example in Claude Code: `/<skill-name>`
3. Output files are saved in `workspace/<name>/`
