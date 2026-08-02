"""Contract tests for the audit module.

Verifies: audit detects known data quality issues and returns structured reports.
Does NOT test: specific rule implementations or diagnostic messages.
"""

from __future__ import annotations

import json

from scrinium.audit import Issue, audit_papers


class TestAuditDetection:
    """Audit contract: reports issues as structured Issue objects."""

    def test_clean_papers_produce_no_errors(self, tmp_papers):
        issues = audit_papers(tmp_papers)
        errors = [i for i in issues if i.severity == "error"]
        # Well-formed test data should have no errors
        assert len(errors) == 0

    def test_missing_doi_reported_for_non_thesis(self, tmp_papers):
        """Paper B is thesis (no DOI ok), but a journal-article without DOI should warn."""
        # Create a journal article without DOI
        d = tmp_papers / "NoDoi-2023-Test"
        d.mkdir()
        (d / "meta.json").write_text(
            json.dumps(
                {
                    "id": "cccc-3333",
                    "title": "Test Paper",
                    "authors": ["Author"],
                    "year": 2023,
                    "doi": "",
                    "paper_type": "journal-article",
                }
            ),
        )
        (d / "paper.md").write_text("# Test Paper\n\nSome content here for testing.")

        issues = audit_papers(tmp_papers)
        doi_issues = [i for i in issues if "doi" in i.rule.lower() or "doi" in i.message.lower()]
        assert len(doi_issues) >= 1

    def test_issue_has_required_fields(self, tmp_papers):
        # Create a problematic paper to guarantee at least one issue
        d = tmp_papers / "Bad-0000-Empty"
        d.mkdir()
        (d / "meta.json").write_text(json.dumps({"id": "bad"}))
        (d / "paper.md").write_text("")

        issues = audit_papers(tmp_papers)
        assert len(issues) > 0
        for issue in issues:
            assert isinstance(issue, Issue)
            assert issue.paper_id
            assert issue.severity in ("error", "warning", "info")
            assert issue.rule
            assert issue.message
