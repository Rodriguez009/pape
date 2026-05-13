from typing import List, Tuple

from .storage import Row


def rank(rows: List[Row], query: str, top_k: int = 10) -> List[Tuple[int, float]]:
    """Return list of (row_index, score) sorted by score desc, score > 0 only."""
    if not rows or not query.strip():
        return []
    # Heavy ML deps loaded only when find is actually invoked (~400ms saved otherwise).
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
    # The default token pattern splits arxiv ids at the dot ("1706.03762" -> "1706", "03762").
    # We append a space-separated copy of the id so queries like "1706.03762" still match.
    def _expand_id(s: str) -> str:
        flat = s.replace(".", " ").replace("/", " ")
        return f"{s} {flat}"

    corpus = [f"{r.title}\n{r.abstract}\n{_expand_id(r.id)}" for r in rows]
    query = f"{query} {query.replace('.', ' ').replace('/', ' ')}"
    # With very small corpora, max_df<1.0 can filter every token out.
    # Only apply the upper cutoff once we have enough documents to make it meaningful.
    max_df = 0.95 if len(rows) >= 20 else 1.0
    vectorizer = TfidfVectorizer(
        lowercase=True,
        stop_words="english",
        ngram_range=(1, 2),
        max_df=max_df,
        min_df=1,
        token_pattern=r"(?u)\b[\w\-\.]{2,}\b",
    )
    try:
        doc_mat = vectorizer.fit_transform(corpus)
        q_vec = vectorizer.transform([query])
    except ValueError:
        return []
    sims = cosine_similarity(q_vec, doc_mat).ravel()
    scored = [(i, float(s)) for i, s in enumerate(sims) if s > 0]
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_k]
