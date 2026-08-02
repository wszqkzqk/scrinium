"""
snowball.py — 库内引用图滚雪球发现
==================================

从一篇或多篇种子论文出发，沿本地引用图做一层扩张（向后参考文献 / 向前被引 /
共享参考文献），按简单透明的规则打分排序，用于快速定位一个领域的核心文献。
打分与组装逻辑集中在此模块，CLI 层（cli/misc.py 的 cmd_snowball）只负责
种子解析与输出；查询原语复用 index.py 的三个引用图函数。
"""

from __future__ import annotations

from pathlib import Path

from scrinium.index import get_citing_papers, get_references, get_shared_references

# Fixed display/JSON order for relation tags.
RELATION_ORDER = ("refs", "citing", "shared")


def snowball_candidates(
    seed_uuids: list[str],
    db_path: Path,
    *,
    ws_ids: set[str] | None = None,
) -> list[dict]:
    """Expand from seed papers along the citation graph and rank candidates.

    Expansion (depth 1, everything within the local library):
      a. backward — in-library references of the seeds (relation ``refs``)
      b. forward — in-library papers citing the seeds (relation ``citing``)
      c. shared — in-library papers sharing >=1 reference with the seeds
         (bibliographic coupling, relation ``shared``)

    Scoring is deliberately simple and transparent:

        score = 2 * shared + 1 * cites_seeds + 1 * cited_by_seeds

    ``shared`` counts the candidate's references that are also references of
    the seeds (matched by DOI, including out-of-library targets);
    ``cites_seeds`` counts how many seeds the candidate cites;
    ``cited_by_seeds`` counts how many seeds reference the candidate.
    Bibliographic coupling is the strongest signal that a paper works on the
    same problem, so it carries double weight. Seeds themselves are excluded.

    Args:
        seed_uuids: UUIDs of the seed papers (>=1).
        db_path: SQLite index database path.
        ws_ids: Optional workspace UUID whitelist restricting candidates.

    Returns:
        Candidate dicts sorted by score desc, then shared refs desc, then
        dir_name. Each dict carries: id, dir_name, title, year, first_author,
        score, shared, cites_seeds, cited_by_seeds, relations (ordered list).
    """
    seeds = set(seed_uuids)
    candidates: dict[str, dict] = {}

    def _add(pid: str, relation: str, row: dict) -> dict | None:
        """Register *pid* as a candidate; skip seeds and out-of-workspace ids."""
        if pid in seeds or (ws_ids is not None and pid not in ws_ids):
            return None
        cand = candidates.setdefault(
            pid,
            {
                "id": pid,
                "dir_name": "",
                "title": "",
                "year": None,
                "first_author": "",
                "shared": 0,
                "cites_seeds": 0,
                "cited_by_seeds": 0,
                "relations": set(),
            },
        )
        cand["relations"].add(relation)
        for key in ("dir_name", "title", "year", "first_author"):
            if row.get(key) and not cand[key]:
                cand[key] = row[key]
        return cand

    # (a) Backward. One aggregated call over all seeds yields every seed
    # reference with the number of seeds citing it (shared_count), plus the
    # full seed-reference DOI set used for coupling scoring below.
    ref_rows = get_shared_references(seed_uuids, db_path, min_shared=1)
    seed_ref_dois = {(r.get("target_doi") or "").strip().lower() for r in ref_rows}
    seed_ref_dois.discard("")
    in_lib_ref_ids: list[str] = []
    for row in ref_rows:
        tid = row.get("target_id")
        if not tid:
            continue
        in_lib_ref_ids.append(tid)
        cand = _add(tid, "refs", row)
        if cand is not None:
            cand["cited_by_seeds"] = max(cand["cited_by_seeds"], row["shared_count"])

    # (b) Forward: in-library papers citing the seeds.
    for sid in seed_uuids:
        for row in get_citing_papers(sid, db_path, paper_ids=ws_ids):
            cand = _add(row["source_id"], "citing", row)
            if cand is not None:
                cand["cites_seeds"] += 1

    # (c) Shared: pivot on each in-library seed reference — every paper citing
    # it shares at least that reference with the seeds. Coupling through
    # out-of-library DOIs cannot be discovered this way (no registry entry to
    # pivot on), but still counts toward the score via the DOI set from (a).
    for ref_id in in_lib_ref_ids:
        for row in get_citing_papers(ref_id, db_path, paper_ids=ws_ids):
            _add(row["source_id"], "shared", row)

    # Score: the shared-reference count needs each candidate's own reference
    # list (DOI-based, so out-of-library targets are included too).
    for pid, cand in candidates.items():
        own_dois = {(r.get("target_doi") or "").strip().lower() for r in get_references(pid, db_path)}
        own_dois.discard("")
        cand["shared"] = len(own_dois & seed_ref_dois)
        cand["score"] = 2 * cand["shared"] + cand["cites_seeds"] + cand["cited_by_seeds"]
        cand["relations"] = [r for r in RELATION_ORDER if r in cand["relations"]]

    return sorted(candidates.values(), key=lambda c: (-c["score"], -c["shared"], c["dir_name"] or c["id"]))
