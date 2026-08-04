# API Reference

::: scrinium.index
    options:
      members:
        - build_index
        - build_proceedings_index
        - search
        - search_author
        - top_cited
        - search_proceedings
        - lookup_paper
        - get_references
        - get_citing_papers
        - get_shared_references

::: scrinium.loader
    options:
      members:
        - load_l1
        - load_l2
        - load_l3
        - load_l4
        - load_notes
        - append_notes
        - enrich_toc
        - validate_lang

::: scrinium.export
    options:
      members:
        - meta_to_bibtex
        - export_bibtex

::: scrinium.audit
    options:
      members:
        - Issue
        - audit_papers

::: scrinium.workspace
    options:
      members:
        - create
        - add
        - remove
        - list_workspaces
        - read_paper_ids

::: scrinium.papers
    options:
      members:
        - paper_dir
        - meta_path
        - md_path
        - iter_paper_dirs

::: scrinium.proceedings
    options:
      members:
        - proceedings_db_path
        - iter_proceedings_dirs
        - iter_proceedings_papers

::: scrinium.tags
    options:
      members:
        - load_taxonomy
        - resolve_tag
        - register_tag
        - paper_tags
        - set_paper_tags
        - all_tags_with_counts
        - papers_with_tag
        - topic_overview

::: scrinium.explore
    options:
      members:
        - fetch_explore
        - explore_search
        - list_explore_libs
        - explore_db_path
        - validate_explore_name

::: scrinium.insights
    options:
      members:
        - extract_hot_keywords
        - aggregate_most_read_titles
        - build_weekly_read_trend
        - recent_unique_read_names
        - list_workspace_counts

::: scrinium.ingest.extractor
    options:
      members:
        - get_extractor

::: scrinium.ingest.metadata
    options:
      members:
        - PaperMetadata
        - enrich_metadata
        - extract_abstract_from_md
        - fetch_abstract_by_doi
        - backfill_abstracts
        - generate_new_stem
        - metadata_to_dict
        - refetch_metadata
        - rename_paper
        - write_metadata_json

::: scrinium.ingest.pipeline
    options:
      members:
        - StepResult
        - InboxCtx
        - run_pipeline
        - import_external
        - batch_convert_pdfs
        - step_index
