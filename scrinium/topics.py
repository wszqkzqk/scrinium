"""
topics.py — BERTopic 主题建模
===============================

复用 paper_vectors 表中的 Qwen3 嵌入向量，通过 BERTopic 对全库论文做主题聚类。
支持全库主题概览、单主题论文列表、层级主题树、主题间关联发现。

用法：
    from scrinium.topics import build_topics, get_topic_overview, get_topic_papers
    model = build_topics(db_path, papers_dir)
    overview = get_topic_overview(model)
    papers = get_topic_papers(model, topic_id=0)
"""

from __future__ import annotations

import logging
import pickle
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, Any

from scrinium.papers import best_citation as _best_cite
from scrinium.papers import read_meta as _read_meta
from scrinium.vectors import _embed_provider, _unpack

_log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from scrinium.config import Config


def _patch_pandas_datetime():
    """Pandas 3.0 compat: BERTopic uses removed infer_datetime_format."""
    import pandas as pd

    if not getattr(pd.to_datetime, "_scrinium_patched", False):
        _orig_dt = pd.to_datetime

        def _patched_dt(*a, **kw):
            kw.pop("infer_datetime_format", None)
            return _orig_dt(*a, **kw)

        _patched_dt._scrinium_patched = True
        pd.to_datetime = _patched_dt


def _load_embeddings_and_docs(
    db_path: Path,
    papers_dir: Path | None = None,
    *,
    papers_map: dict[str, dict] | None = None,
) -> tuple[list[str], list[str], list[dict], np.ndarray]:
    """从 DB 加载向量，从 JSON 或 papers_map 加载文档文本和元数据。

    Args:
        db_path: SQLite 数据库路径（含 paper_vectors 表）。
        papers_dir: 论文 JSON 目录（主库模式）。与 ``papers_map`` 二选一。
        papers_map: paper_id → 元数据字典映射（explore 模式）。
            提供时跳过 meta.json 读取，直接从映射中获取元数据。

    Returns:
        ``(paper_ids, docs, metas, embeddings)`` 四元组。
        docs 为 title + abstract 拼接文本，用于 BERTopic 的 c-TF-IDF。

    Raises:
        FileNotFoundError: 数据库或向量表不存在。
    """
    import numpy as np

    if not db_path.exists():
        raise FileNotFoundError(f"索引文件不存在：{db_path}\n请先运行 `scrinium index`")

    conn = sqlite3.connect(db_path)
    try:
        has_vectors = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='paper_vectors'"
        ).fetchone()
        if not has_vectors:
            raise FileNotFoundError("向量索引不存在，请先运行 `scrinium embed`")

        rows = conn.execute("SELECT paper_id, embedding FROM paper_vectors").fetchall()
    finally:
        conn.close()

    paper_ids = []
    docs = []
    metas = []
    vecs = []

    if papers_map is not None:
        # Explore mode: metadata comes from pre-built map
        for paper_id, blob in rows:
            p = papers_map.get(paper_id)
            if p is None:
                continue

            title = (p.get("title") or "").strip()
            abstract = (p.get("abstract") or "").strip()
            text = f"{title}. {abstract}" if abstract else title
            if not text.strip():
                continue

            # Normalize citation: explore uses cited_by_count (int),
            # main library uses citation_count (dict)
            cite = p.get("citation_count")
            if cite is None:
                cbc = p.get("cited_by_count", 0)
                cite = {"openalex": cbc} if cbc else {}

            authors = p.get("authors", [])
            if isinstance(authors, list):
                authors = ", ".join(authors)

            paper_ids.append(paper_id)
            docs.append(text)
            metas.append(
                {
                    "paper_id": paper_id,
                    "title": title,
                    "authors": authors,
                    "year": p.get("year", ""),
                    "journal": p.get("journal", ""),
                    "citation_count": cite,
                }
            )
            vecs.append(_unpack(blob))
    else:
        # Main library mode: metadata from meta.json files
        id_to_dir: dict[str, str] = {}
        try:
            reg_conn = sqlite3.connect(db_path)
            for row in reg_conn.execute("SELECT id, dir_name FROM papers_registry").fetchall():
                id_to_dir[row[0]] = row[1]
            reg_conn.close()
        except Exception as e:
            _log.debug("failed to load papers_registry: %s", e)

        for paper_id, blob in rows:
            dir_name = id_to_dir.get(paper_id, paper_id)
            paper_d = papers_dir / dir_name
            json_file = paper_d / "meta.json"
            if not json_file.exists():
                continue

            try:
                meta = _read_meta(paper_d)
            except (ValueError, FileNotFoundError) as e:
                _log.debug("failed to read meta.json in %s: %s", paper_d.name, e)
                continue

            title = (meta.get("title") or "").strip()
            abstract = (meta.get("abstract") or "").strip()
            text = f"{title}. {abstract}" if abstract else title
            if not text.strip():
                continue

            paper_ids.append(paper_id)
            docs.append(text)
            metas.append(
                {
                    "paper_id": paper_id,
                    "title": title,
                    "authors": ", ".join(meta.get("authors") or []),
                    "year": meta.get("year", ""),
                    "journal": meta.get("journal", ""),
                    "citation_count": meta.get("citation_count", {}),
                }
            )
            vecs.append(_unpack(blob))

    embeddings = np.array(vecs, dtype="float32")
    return paper_ids, docs, metas, embeddings


# ============================================================================
#  Build
# ============================================================================


def _fit_bertopic(
    docs: list[str],
    embeddings: np.ndarray,
    *,
    min_topic_size: int = 5,
    nr_topics: int | str | None = "auto",
    n_neighbors: int | None = None,
    n_components: int = 5,
    min_samples: int = 2,
    ngram_range: tuple[int, int] = (1, 3),
    min_df: int = 2,
    top_n_words: int = 10,
    cfg: Config | None = None,
) -> tuple[BERTopic, list[int]]:
    """Fit a BERTopic model with the given hyperparameters.

    Core BERTopic pipeline shared by both the main library (``build_topics``)
    and explore silos (``build_explore_topics``).  Handles UMAP + HDBSCAN +
    CountVectorizer + KeyBERTInspired + outlier reduction.

    Args:
        docs: Document strings (one per paper).
        embeddings: Pre-computed embedding matrix ``(n_papers, dim)``.
        min_topic_size: ``HDBSCAN.min_cluster_size``.
        nr_topics: Target topic count (``"auto"`` / ``None`` / int).
        n_neighbors: UMAP ``n_neighbors``.  Defaults to ``min(15, n//10)``.
        n_components: UMAP ``n_components``.
        min_samples: HDBSCAN ``min_samples``.
        ngram_range: CountVectorizer ``ngram_range``.
        min_df: CountVectorizer ``min_df``.
        top_n_words: BERTopic ``top_n_words``.
        cfg: Optional config for embedding model.

    Returns:
        ``(topic_model, topics)`` — fitted model and topic assignments.
    """

    from bertopic import BERTopic
    from bertopic.representation import KeyBERTInspired, MaximalMarginalRelevance
    from hdbscan import HDBSCAN
    from sklearn.feature_extraction.text import CountVectorizer
    from umap import UMAP

    from scrinium.vectors import QwenEmbedder

    n = len(docs)
    if n_neighbors is None:
        n_neighbors = min(15, max(5, n // 10))

    umap_model = UMAP(
        n_neighbors=n_neighbors,
        n_components=n_components,
        min_dist=0.0,
        metric="cosine",
        random_state=42,
    )
    hdbscan_model = HDBSCAN(
        min_cluster_size=min_topic_size,
        min_samples=min_samples,
        metric="euclidean",
        prediction_data=True,
    )
    # When corpus is very small, min_df=2 can exceed the number of docs
    # in a cluster, causing CountVectorizer to raise ValueError.
    effective_min_df = min(min_df, max(1, n // 4))
    vectorizer_model = CountVectorizer(
        stop_words="english",
        ngram_range=ngram_range,
        min_df=effective_min_df,
    )
    embedder = QwenEmbedder(cfg)
    representation_model = [
        KeyBERTInspired(),
        MaximalMarginalRelevance(diversity=0.3),
    ]

    topic_model = BERTopic(
        embedding_model=embedder,
        umap_model=umap_model,
        hdbscan_model=hdbscan_model,
        vectorizer_model=vectorizer_model,
        representation_model=representation_model,
        nr_topics=nr_topics,
        top_n_words=top_n_words,
        verbose=True,
    )

    topics, _ = topic_model.fit_transform(docs, embeddings=embeddings)

    # Reduce outliers by assigning them to nearest topic
    n_outliers_before = sum(1 for t in topics if t == -1)
    n_real_topics = len(set(topics) - {-1})
    if n_outliers_before > 0 and n_real_topics > 0:
        topics = topic_model.reduce_outliers(docs, topics, strategy="embeddings", embeddings=embeddings)
        topic_model.update_topics(
            docs,
            topics=topics,
            vectorizer_model=vectorizer_model,
            representation_model=representation_model,
        )
        n_outliers_after = sum(1 for t in topics if t == -1)
        _log.info("Outlier reduction: %d → %d", n_outliers_before, n_outliers_after)

    return topic_model, list(topics) if not isinstance(topics, list) else topics


def build_topics(
    db_path: Path,
    papers_dir: Path | None = None,
    *,
    papers_map: dict[str, dict] | None = None,
    min_topic_size: int = 5,
    nr_topics: int | str | None = "auto",
    save_path: Path | None = None,
    cfg: Config | None = None,
    **fit_kwargs: Any,
) -> BERTopic:
    """构建 BERTopic 主题模型。

    复用 ``paper_vectors`` 表中已有的嵌入向量，不重新编码。
    使用 UMAP 降维 + HDBSCAN 聚类 + c-TF-IDF 提取主题关键词。

    Args:
        db_path: SQLite 数据库路径。
        papers_dir: 论文 JSON 目录（主库模式）。与 ``papers_map`` 二选一。
        papers_map: paper_id → 元数据字典映射（explore 模式）。
        min_topic_size: 最小主题大小（HDBSCAN ``min_cluster_size``）。
        nr_topics: 目标主题数。``"auto"`` 自动合并；``None`` 不合并；整数指定数量。
        save_path: 模型保存路径，为 ``None`` 时不保存。
        cfg: 可选配置。
        **fit_kwargs: 传递给 ``_fit_bertopic()`` 的额外参数
            （如 ``n_neighbors``, ``n_components``, ``ngram_range`` 等）。

    Returns:
        训练好的 BERTopic 模型实例。
    """
    if _embed_provider(cfg) == "none":
        raise FileNotFoundError("当前 embed.provider=none，无法构建主题模型，请先启用向量后端并运行 embed")

    paper_ids, docs, metas, embeddings = _load_embeddings_and_docs(
        db_path,
        papers_dir,
        papers_map=papers_map,
    )
    _log.info("Loaded vectors and text for %d papers", len(docs))

    # Use cfg as fallback for default values only
    if cfg is not None and hasattr(cfg, "topics"):
        tc = cfg.topics
        if min_topic_size == 5:  # default
            min_topic_size = tc.min_topic_size
        if nr_topics == "auto":  # default
            if tc.nr_topics == 0:
                nr_topics = "auto"
            elif tc.nr_topics == -1:
                nr_topics = None
            else:
                nr_topics = tc.nr_topics

    topic_model, topics = _fit_bertopic(
        docs,
        embeddings,
        min_topic_size=min_topic_size,
        nr_topics=nr_topics,
        cfg=cfg,
        **fit_kwargs,
    )

    # Attach metadata for later retrieval
    topic_model._paper_ids = paper_ids
    topic_model._metas = metas
    topic_model._topics = topics
    topic_model._embeddings = embeddings
    topic_model._docs = docs

    if save_path:
        save_path.parent.mkdir(parents=True, exist_ok=True)
        _save_model(topic_model, save_path)
        _log.info("Model saved: %s", save_path)

    n_topics = len(set(topics)) - (1 if -1 in topics else 0)
    n_outliers = topics.count(-1) if isinstance(topics, list) else sum(1 for t in topics if t == -1)
    _log.info("Found %d topics, %d outliers", n_topics, n_outliers)

    return topic_model


# ============================================================================
#  Query
# ============================================================================


def get_topic_overview(model: BERTopic) -> list[dict]:
    """获取所有主题的概览信息。

    Args:
        model: 已训练的 BERTopic 模型。

    Returns:
        主题字典列表，每项包含 ``topic_id``, ``count``, ``name``,
        ``keywords``（前 10 关键词）, ``representative_papers``。
    """
    info = model.get_topic_info()
    metas = getattr(model, "_metas", [])
    topics_list = getattr(model, "_topics", [])

    overview = []
    for _, row in info.iterrows():
        tid = row["Topic"]
        if tid == -1:
            continue

        # Get keywords
        topic_words = model.get_topic(tid)
        keywords = [w for w, _ in topic_words[:10]] if topic_words else []

        # Get papers in this topic
        papers = []
        for idx, t in enumerate(topics_list):
            if t == tid and idx < len(metas):
                papers.append(metas[idx])

        papers.sort(key=_best_cite, reverse=True)

        overview.append(
            {
                "topic_id": tid,
                "count": int(row["Count"]),
                "name": row.get("Name", ""),
                "keywords": keywords,
                "representative_papers": papers[:5],
            }
        )

    overview.sort(key=lambda x: x["count"], reverse=True)
    return overview


def get_topic_papers(model: BERTopic, topic_id: int) -> list[dict]:
    """获取指定主题的全部论文。

    Args:
        model: 已训练的 BERTopic 模型。
        topic_id: 主题 ID。

    Returns:
        该主题下所有论文的元数据列表。
    """
    metas = getattr(model, "_metas", [])
    topics_list = getattr(model, "_topics", [])

    papers = []
    for idx, t in enumerate(topics_list):
        if t == topic_id and idx < len(metas):
            papers.append(metas[idx])

    papers.sort(key=_best_cite, reverse=True)
    return papers


def get_outliers(model: BERTopic) -> list[dict]:
    """获取未被归入任何主题的论文（outlier，topic_id == -1）。

    Args:
        model: 已训练的 BERTopic 模型。

    Returns:
        outlier 论文的元数据列表。
    """
    return get_topic_papers(model, topic_id=-1)


def find_related_topics(model: BERTopic, paper_id: str) -> list[dict]:
    """查找与指定论文最相关的其他主题。

    通过论文所属主题的相似度矩阵，找出关联最强的主题。

    Args:
        model: 已训练的 BERTopic 模型。
        paper_id: 论文 ID。

    Returns:
        相关主题列表（不含论文自身所属主题），按相似度降序。
    """
    paper_ids = getattr(model, "_paper_ids", [])
    topics_list = getattr(model, "_topics", [])

    if paper_id not in paper_ids:
        return []

    idx = paper_ids.index(paper_id)
    current_topic = topics_list[idx]

    if current_topic == -1:
        return []

    # Use topic similarity matrix
    try:
        sim_matrix = model.topic_similarities_
    except AttributeError:
        try:
            from sklearn.metrics.pairwise import cosine_similarity

            sim_matrix = cosine_similarity(model.c_tf_idf_.toarray())
        except Exception as e:
            _log.debug("failed to compute topic similarities: %s", e)
            return []

    topic_ids = sorted(set(topics_list) - {-1})
    if current_topic not in topic_ids:
        return []

    tid_to_idx = {t: i for i, t in enumerate(topic_ids)}
    cur_idx = tid_to_idx[current_topic]

    related = []
    for tid in topic_ids:
        if tid == current_topic:
            continue
        sim = float(sim_matrix[cur_idx][tid_to_idx[tid]])
        topic_words = model.get_topic(tid)
        keywords = [w for w, _ in topic_words[:5]] if topic_words else []
        related.append(
            {
                "topic_id": tid,
                "similarity": sim,
                "keywords": keywords,
            }
        )

    related.sort(key=lambda x: x["similarity"], reverse=True)
    return related


# ============================================================================
#  Visualization (returns HTML strings for saving)
# ============================================================================


def visualize_topic_hierarchy(model: BERTopic, docs: list[str] | None = None) -> str:
    """生成主题层级树的 HTML 可视化。

    Args:
        model: 已训练的 BERTopic 模型。
        docs: 原始文档列表（可选，用于层级聚类）。

    Returns:
        Plotly HTML 字符串。
    """
    fig = model.visualize_hierarchy()
    return fig.to_html(include_plotlyjs="cdn")


def visualize_topics_2d(model: BERTopic) -> str:
    """生成主题 2D 散点图（每篇论文一个点，同 topic 同色）。

    Args:
        model: 已训练的 BERTopic 模型。

    Returns:
        Plotly HTML 字符串。
    """
    embeddings = getattr(model, "_embeddings", None)
    docs = getattr(model, "_docs", [])
    metas = getattr(model, "_metas", [])

    if embeddings is None or len(docs) == 0:
        # Fallback to topic-level visualization
        _log.warning("No embeddings stored; falling back to topic-level viz")
        fig = model.visualize_topics()
        return fig.to_html(include_plotlyjs="cdn")

    from umap import UMAP

    reduced = UMAP(n_components=2, min_dist=0.0, metric="cosine", random_state=42).fit_transform(embeddings)

    # Build hover labels: Author (Year) Title
    hover_labels = []
    for i, d in enumerate(docs):
        if i < len(metas):
            m = metas[i]
            author = (m.get("authors", "") or "").split(",")[0].strip()
            year = m.get("year", "?")
            title = (m.get("title", "") or "")[:60]
            hover_labels.append(f"{author} ({year}) {title}")
        else:
            hover_labels.append(d[:60])

    # Build short topic labels: "Topic N: kw1, kw2, kw3"
    topic_info = model.get_topic_info()
    custom_labels = {}
    for _, row in topic_info.iterrows():
        tid = row["Topic"]
        # get top 3 keywords from the topic representation
        top_words = model.get_topic(tid)
        if top_words and isinstance(top_words, list):
            kw = ", ".join(w for w, _ in top_words[:3])
        else:
            kw = ""
        custom_labels[tid] = f"Topic {tid}: {kw}" if kw else f"Topic {tid}"
    model.set_topic_labels(custom_labels)

    fig = model.visualize_documents(
        docs=hover_labels,
        reduced_embeddings=reduced,
        hide_document_hover=False,
        custom_labels=True,
    )

    # Shorten on-plot annotations to just "Topic N", keep legend full
    for ann in fig.layout.annotations:
        if ann.text and ann.text.startswith("Topic "):
            # Extract "Topic N" from "Topic N: kw1, kw2, ..."
            short = ann.text.split(":")[0]
            ann.text = f"<b>{short}</b>"

    # Restore original labels so other visualizations are unaffected
    model.custom_labels_ = None

    return fig.to_html(include_plotlyjs="cdn")


def visualize_barchart(model: BERTopic, top_n_topics: int = 10) -> str:
    """生成主题关键词条形图的 HTML 可视化。

    Args:
        model: 已训练的 BERTopic 模型。
        top_n_topics: 展示前 N 个主题。

    Returns:
        Plotly HTML 字符串。
    """
    fig = model.visualize_barchart(top_n_topics=top_n_topics, n_words=8, width=280, height=280)
    return fig.to_html(include_plotlyjs="cdn")


def visualize_heatmap(model: BERTopic) -> str:
    """生成主题间相似度热力图的 HTML 可视化。

    Args:
        model: 已训练的 BERTopic 模型。

    Returns:
        Plotly HTML 字符串。
    """
    n_topics = len(model.get_topic_freq())
    fig = model.visualize_heatmap(top_n_topics=min(n_topics, 64))
    return fig.to_html(include_plotlyjs="cdn")


def visualize_term_rank(model: BERTopic) -> str:
    """生成主题词频排名曲线的 HTML 可视化。

    Args:
        model: 已训练的 BERTopic 模型。

    Returns:
        Plotly HTML 字符串。
    """
    fig = model.visualize_term_rank()
    return fig.to_html(include_plotlyjs="cdn")


def visualize_topics_over_time(model: BERTopic) -> str:
    """生成主题随时间变化趋势的 HTML 可视化。

    利用论文的发表年份，按时间分箱统计各主题的论文数变化。

    Args:
        model: 已训练的 BERTopic 模型。

    Returns:
        Plotly HTML 字符串。

    Raises:
        ValueError: 无法生成时间趋势（缺少年份数据等）。
    """
    import pandas as pd  # noqa: F401 (needed by BERTopic internals)

    _patch_pandas_datetime()

    docs = getattr(model, "_docs", [])
    metas = getattr(model, "_metas", [])

    if not docs or not metas:
        raise ValueError("模型中缺少文档或元数据，无法生成时间趋势")

    timestamps = [f"{m.get('year', 2000)}-01-01" for m in metas]

    # Temporarily disable representation model to avoid re-embedding
    saved_repr = model.representation_model
    model.representation_model = None
    try:
        tot = model.topics_over_time(docs, timestamps, nr_bins=15)
        fig = model.visualize_topics_over_time(tot, top_n_topics=20)
    finally:
        model.representation_model = saved_repr

    return fig.to_html(include_plotlyjs="cdn")


def reduce_topics_to(
    model: BERTopic, nr_topics: int, save_path: Path | None = None, cfg: Config | None = None
) -> BERTopic:
    """在已有模型上快速合并主题到指定数量（不重新聚类）。

    Args:
        model: 已训练的 BERTopic 模型。
        nr_topics: 目标主题数。
        save_path: 模型保存路径，为 ``None`` 时不保存。
        cfg: 可选配置（用于初始化嵌入模型）。

    Returns:
        合并后的 BERTopic 模型实例。
    """
    docs = getattr(model, "_docs", [])
    if not docs:
        raise ValueError("模型中缺少文档数据，无法合并主题")

    # Re-attach embedding model if missing (loaded models don't have it)
    if model.embedding_model is None:
        from scrinium.vectors import QwenEmbedder

        model.embedding_model = QwenEmbedder(cfg)

    model.reduce_topics(docs, nr_topics=nr_topics)

    # Update stored topics list
    model._topics = list(model.topics_)

    if save_path:
        _save_model(model, save_path)
        _log.info("Model saved after reduction: %s", save_path)

    n_topics = len(set(model._topics)) - (1 if -1 in model._topics else 0)
    _log.info("Reduced to %d topics", n_topics)

    return model


def merge_topics_by_ids(
    model: BERTopic,
    topics_to_merge: list[list[int]],
    save_path: Path | None = None,
    cfg: Config | None = None,
) -> BERTopic:
    """手动合并指定主题（供 Claude Code 调用）。

    Args:
        model: 已训练的 BERTopic 模型。
        topics_to_merge: 要合并的主题 ID 列表，如 ``[[1, 6, 14], [3, 5]]``
            表示将 1/6/14 合并为一个主题，3/5 合并为一个主题。
        save_path: 模型保存路径，为 ``None`` 时不保存。
        cfg: 可选配置（用于初始化嵌入模型）。

    Returns:
        合并后的 BERTopic 模型实例。
    """
    docs = getattr(model, "_docs", [])
    if not docs:
        raise ValueError("模型中缺少文档数据，无法合并主题")

    # Re-attach embedding model if missing (loaded models don't have it)
    if model.embedding_model is None:
        from scrinium.vectors import QwenEmbedder

        model.embedding_model = QwenEmbedder(cfg)

    model.merge_topics(docs, topics_to_merge)

    # Update stored topics list
    model._topics = list(model.topics_)

    if save_path:
        _save_model(model, save_path)
        _log.info("Model saved after merge: %s", save_path)

    n_topics = len(set(model._topics)) - (1 if -1 in model._topics else 0)
    _log.info("Merged to %d topics", n_topics)

    return model


# ============================================================================
#  Persistence
# ============================================================================


def _save_model(model: BERTopic, path: Path) -> None:
    """保存 BERTopic 模型及附加元数据。

    Args:
        model: 已训练的 BERTopic 模型。
        path: 保存目录路径。
    """
    path.mkdir(parents=True, exist_ok=True)

    # Save custom attributes separately
    custom = {
        "paper_ids": getattr(model, "_paper_ids", []),
        "metas": getattr(model, "_metas", []),
        "topics": getattr(model, "_topics", []),
        "embeddings": getattr(model, "_embeddings", None),
        "docs": getattr(model, "_docs", []),
    }
    custom_path = path / "scrinium_meta.pkl"
    with open(custom_path, "wb") as f:
        pickle.dump(custom, f)

    # BERTopic pickle save expects a file path, not a directory
    model_file = path / "bertopic_model.pkl"
    model.save(str(model_file), serialization="pickle", save_embedding_model=False)


def load_model(path: Path) -> BERTopic:
    """加载已保存的 BERTopic 模型。

    Args:
        path: 模型目录路径。

    Returns:
        加载的 BERTopic 模型实例（含附加元数据）。

    Raises:
        FileNotFoundError: 模型文件不存在。
    """
    from bertopic import BERTopic

    model_file = path / "bertopic_model.pkl"
    if not model_file.exists():
        # Backward compat: old explore models saved as model.pkl
        legacy = path / "model.pkl"
        if legacy.exists():
            model_file = legacy
        else:
            raise FileNotFoundError(f"主题模型不存在：{path}\n请先运行 `scrinium topics --build`")

    model = BERTopic.load(str(model_file))

    # Restore custom attributes
    custom_path = path / "scrinium_meta.pkl"
    if custom_path.exists():
        with open(custom_path, "rb") as f:
            custom = pickle.load(f)
        model._paper_ids = custom.get("paper_ids", [])
        model._metas = custom.get("metas", [])
        model._topics = custom.get("topics", [])
        model._embeddings = custom.get("embeddings", None)
        model._docs = custom.get("docs", [])

    return model
