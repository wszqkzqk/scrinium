# Onboarding a Scientific Tool

ScholarAIO can index official documentation for scientific computing tools through `toolref`.

This guide is for users and external contributors who want to add support for a new tool without reverse-engineering the current codebase. It focuses on the public workflow and the quality bar for a production-ready integration.

## When a New Tool Is Worth Adding

Add a new tool when all of the following are true:

- users are likely to ask for the tool in natural language during real scientific work
- the tool has an official documentation source that is stable enough to index
- the tool has high-value commands, parameters, or workflows that benefit from reliable lookup
- the integration can improve user task completion, not just increase page count

Do not add a tool just because documentation exists somewhere online. A useful integration should improve `show` and `search` behavior for the queries users actually type.

## The Public Contract

The stable public surfaces are:

- `scholaraio toolref fetch <tool>`
- `scholaraio toolref list [tool]`
- `scholaraio toolref show <tool> ...`
- `scholaraio toolref search <tool> "..."`
- `scholaraio toolref use <tool> <version>` — switch the active version
- the top-level Python facade `scholaraio.toolref`

User-facing documentation should stay anchored to those surfaces.

Do not teach users to depend on internal modules such as:

- `scholaraio.toolref.fetch`
- `scholaraio.toolref.manifest`
- `scholaraio.toolref.storage`
- `scholaraio.toolref.search`

Those modules exist for implementation, not as the public onboarding surface.

## Choose an Ingestion Mode

ScholarAIO currently uses two onboarding patterns.

### `git + parser`

Choose this when:

- the official docs evolve with the source repository
- versioned tags or releases are meaningful
- the docs are structured enough that a parser can extract high-value entries

Current examples:

- Quantum ESPRESSO
- LAMMPS
- GROMACS

### `manifest + discovery`

Choose this when:

- the official docs live on a documentation site rather than in a repository snapshot
- the highest-value pages are a subset of a larger portal
- discovery, anchor extraction, and cache preservation matter more than mirroring the whole site

Current examples:

- OpenFOAM
- Bioinformatics toolchain docs

Do not choose a mode based on theoretical completeness alone. Choose the mode that produces the most reliable user experience for `show` and `search`.

## Version Rules

User-facing versions should use the version vocabulary that users understand.

Examples:

- `7.5`
- `2312`
- `22Jul2025_update3`

Do not expose internal tag-prefix details as part of the user contract. If the upstream repository uses a tag naming convention, that is an implementation detail.

The integration should also support multiple local versions and a current active version. By default, `show` and `search` should resolve against the current version unless the user explicitly switches or fetches another one.

## Design `page_name`, `program`, and `section` for Real Queries

These fields are not just storage metadata. They define whether the tool feels usable.

### `page_name`

`page_name` should be:

- stable across refreshes when possible
- specific enough for direct lookup
- designed for `show`, not only for crawling convenience

Good `page_name` values help users reach the right page directly:

- `pw.x/SYSTEM/ecutwfc`
- `openfoam/forceCoeffs`
- `samtools/index`

Avoid naming pages in a way that only reflects the upstream URL structure if that makes direct lookup awkward.

### `program`

`program` should match the name users will actually say.

Examples:

- `pw.x`
- `simpleFoam`
- `samtools`
- `bcftools`

For toolchains, `program` is especially important because the first task is often routing the query to the correct sub-tool.

### `section`

`section` should reflect how users reason about the docs.

Examples:

- `SYSTEM`
- `solver`
- `dictionary`
- `post-processing`
- `variant-calling`

Use `section` to improve lookup and search quality, not as an arbitrary bucket.

## Start With the Smallest Useful Surface

Do not try to ingest an entire upstream site on day one.

Start with the pages that matter most:

- the most-used program or solver pages
- the highest-risk parameter pages
- the main configuration or dictionary pages
- a small number of common post-processing or analysis pages

The goal is not "every page exists". The goal is:

- high-value `show` queries hit directly
- high-value `search` queries rank the right page first
- refreshes do not silently reduce usable coverage

## Natural-Language Query Quality Is a Hard Requirement

A tool is not ready just because canonical parameter names work.

Each integration should validate at least three query styles:

### Parameter-style queries

Examples:

- `ecutwfc`
- `pcoupl`
- `samtools index`

### Natural-language queries

Examples:

- `drag coefficient`
- `pressure coupling`
- `multiple sequence alignment`

### Task-oriented queries

Examples:

- `read mapping nanopore`
- `variant calling vcf`
- `solver residuals`

The production bar is not "some result appears". The production bar is "the top result is usually the page the user intended".

## Toolchain Routing Comes Before Coverage

For ecosystems with multiple programs or sub-tools, onboarding must first solve routing.

If a user asks:

- `read mapping nanopore`
- `variant calling vcf`
- `phylogenetic tree bootstrap`

the integration should steer those queries toward the correct program before worrying about broader page expansion.

For toolchains, getting the right `program` is often more important than adding many more pages.

## Minimum End-to-End Loop

Every new tool should satisfy this minimal loop:

```bash
scholaraio toolref fetch <tool>
scholaraio toolref list <tool>
scholaraio toolref show <tool> <natural query>
scholaraio toolref search <tool> "<real query>"
```

What to verify:

- `fetch` completes and leaves a usable local version
- `list` shows believable version and page counts
- `show` can hit a high-value page using natural input
- `search` ranks the intended page near the top

If that loop does not feel good during manual use, the integration is not ready, even if unit tests pass.

## Reliability Rules for Refresh and Discovery

The current mature `toolref` integrations follow a few important rules:

- a refresh must not silently replace a more complete local cache with a worse one
- discovered page sets should be reproducible, not guessed differently on every run
- high-value pages may need fallback sources when the primary source is flaky
- the final reported counts should match what users can actually query

For contributors, the practical lesson is simple:

- optimize for stable, repeatable user behavior
- do not optimize only for raw crawl breadth

## What "Production-Ready" Means

For ScholarAIO, a production-ready scientific tool integration means:

- the most important `show` queries directly hit the correct page
- the most important `search` queries usually rank the correct page first
- multiple versions can coexist without confusing the default behavior
- refreshes do not degrade the integration quietly
- users can continue their scientific task even when coverage is still partial

It does not mean:

- the entire upstream site has been mirrored
- every possible page has been parsed
- every obscure edge case has first-class coverage

## Minimal Onboarding Example

Suppose you want to onboard a fictional tool called `mysolver`.

### 1. Pick the source model

- If `mysolver` ships structured docs in a versioned repository, prefer `git + parser`
- If `mysolver` exposes a docs portal with a few important pages and stable navigation, prefer `manifest + discovery`

### 2. Define the first useful pages

Examples:

- `mysolver/run`
- `mysolver/input`
- `mysolver/convergence`

If it is a multi-program ecosystem:

- `mytool/preprocess`
- `mytool/solve`
- `mytool/analyze`

### 3. Define real queries before broadening coverage

Examples:

- parameter-style: `timestep`
- natural-language: `adaptive time step`
- task-style: `post process pressure field`

### 4. Validate the public loop

```bash
scholaraio toolref fetch mysolver
scholaraio toolref list mysolver
scholaraio toolref show mysolver timestep
scholaraio toolref search mysolver "adaptive time step"
```

If those queries are not convincing yet, improve naming, routing, and ranking before adding more pages.

## Checklist

Before considering a new tool "ready enough", confirm:

- the tool has a clear official documentation source
- the chosen ingestion mode matches the shape of the upstream docs
- `page_name`, `program`, and `section` were designed for user queries
- natural-language and task-oriented queries were tested, not only canonical names
- `fetch`, `list`, `show`, and `search` all work end to end
- the integration behaves sensibly with more than one version
- refreshes do not silently reduce usable coverage

When in doubt, prefer a smaller, more reliable integration over a larger but unstable one.
