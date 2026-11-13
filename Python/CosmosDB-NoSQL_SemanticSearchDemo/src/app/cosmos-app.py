"""Original Streamlit controls backed by standalone Azure Data AI reranking."""

from pathlib import Path
import logging
import os
import sys

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import search_demo as demo

logger = logging.getLogger("search_demo.ui")

st.set_page_config(page_title="Azure Cosmos DB Semantic Search Demo", layout="wide",
                   initial_sidebar_state="expanded")

INDEX_NAMES = {
    "QFLAT & Full Text Search Index": "search_qflat",
    "DiskANN & Full Text Search Index": "search_diskann",
}
TARGET_FIELDS = {
    "Title and Description": ("title", "text"),
    "Title only": ("title",),
    "Description only": ("text",),
}
DATASET_SOURCE = (
    "https://github.com/TheovanKraay/AzureDataRetrievalAugmentedGenerationSamples/"
    "blob/7fd162fc633617857f8b8ed2c5b2b92d4d8ef0b6/DataSet/Movies/MovieLens-4489-256D.json"
)


def run_search(mode):
    # Clear old success before any operation, including embedding/configuration failures.
    st.session_state.pop("search_result", None)
    st.session_state.pop("suggested_listings", None)
    st.session_state.pop("search_error", None)
    try:
        enabled = st.session_state.get("use_reranker", False)
        options = None
        if enabled:
            options = demo.RerankOptions(
                document_format=st.session_state.get("rerank_format", "text"),
                target_paths=TARGET_FIELDS.get(st.session_state.get(
                    "rerank_fields", "Title and Description"), ()),
                top_k=st.session_state.get("rerank_top_k", 10),
                return_sentence_scores=st.session_state.get("sentence_diagnostics", False))
            options.validate()
        result = demo.search(
            demo.get_container(INDEX_NAMES[st.session_state.index_selection]),
            mode, st.session_state.user_query,
            use_reranker=enabled,
            search_type=st.session_state.get("full_text_search_type", "all keywords"),
            rerank_options=options)
        listings = pd.DataFrame(
            [{k: v for k, v in row.items() if k != "sentence_scores"} for row in result.rows])
        st.session_state.search_result = result
        st.session_state.suggested_listings = listings
    except Exception as exc:
        # Private developer terminal only. SDK tracebacks may contain sensitive details.
        logger.exception("Search request failed.")
        st.session_state.pop("search_result", None)
        st.session_state.pop("suggested_listings", None)
        # Only our SearchError contract is UI-safe, not arbitrary SDK ValueErrors.
        st.session_state.search_error = (
            str(exc) if isinstance(exc, demo.SearchError) else
            "Search could not complete. Check search input, reranking options, environment "
            "settings, Azure CLI/managed identity, resource permissions and network access.")


with st.sidebar:
    st.selectbox("Index", options=list(INDEX_NAMES), index=0, key="index_selection")
    st.text_input("Search input", placeholder="Woody Buzz", key="user_query")
    st.checkbox("Use Semantic Reranker", key="use_reranker",
                help="Apply semantic reranking with the standalone Azure Data AI inference service")
    with st.expander("Advanced reranking", expanded=False):
        advanced_disabled = not st.session_state.use_reranker
        st.selectbox("Document format", ["text", "json"], key="rerank_format",
                     disabled=advanced_disabled)
        st.selectbox("JSON fields", list(TARGET_FIELDS), key="rerank_fields",
                     disabled=advanced_disabled or st.session_state.rerank_format != "json")
        st.caption("Description maps to the text field. Only selected JSON fields are sent.")
        st.number_input("Rerank result limit", min_value=1, max_value=10, value=10, step=1,
                        key="rerank_top_k", disabled=advanced_disabled)
        st.checkbox("Sentence-score diagnostics", key="sentence_diagnostics",
                    disabled=advanced_disabled)
        st.caption("Service sentence indices are not mapped to source text or JSON fields.")
    disabled = not st.session_state.user_query.strip()
    st.button("Similarity search", key="location_search", disabled=disabled,
              on_click=run_search, args=("vector",))
    st.button("Full text ranking", key="full_text_ranking", disabled=disabled,
              on_click=run_search, args=("ranking",))
    st.button("Hybrid search", key="hybrid_search", disabled=disabled,
              on_click=run_search, args=("hybrid",))
    st.radio("Search type", options=["all keywords", "any keywords"], key="full_text_search_type")
    st.button("Full text search", key="full_text_search", disabled=disabled,
              on_click=run_search, args=("fulltext",))
    st.write("---")
    st.markdown("[Cosmos DB Samples Gallery](https://azurecosmosdb.github.io/gallery/)")
    st.markdown("[GitHub](https://github.com/microsoft/AzureDataRetrievalAugmentedGenerationSamples)")

st.title("Azure Cosmos DB - Semantic Search Demo")
st.write("Showcasing vector search, full text search, text ranking, hybrid search, "
         "and semantic reranking capabilities.")
with st.container(border=True):
    st.markdown("**Default source corpus: MovieLens**")
    st.markdown(
        "4,489 source rows of movie metadata and plot overviews, including Toy Story "
        "and Grumpier Old Men. "
        f"[View pinned MovieLens source]({DATASET_SOURCE})")
    st.markdown(
        "Default `azd up` restores every source row with fresh 1536-dimensional embeddings. "
        "With custom data, use searches suited to your documents. "
        "This describes the source corpus, not a live inventory of the selected container.")
    st.markdown(
        "**Example searches for MovieLens:** "
        "Full text: `Woody Buzz` or `fishing buddies`. "
        "Similarity / hybrid: `toys learning to share a child's affection`.")
    # Configuration only: do not resolve clients or inspect the container on a rerun.
    demo.load_environment()
    database = os.getenv("COSMOS_DB_DATABASE", "").strip() or "Not configured"
    st.text(f"Configured database: {database} | "
            f"Selected container: {INDEX_NAMES[st.session_state.index_selection]}")
st.write("---")

if st.session_state.get("search_error"):
    st.error(st.session_state.search_error)
elif "search_result" in st.session_state:
    result = st.session_state.search_result
    st.write(f"Executed query: {result.query}")
    st.write(f"Embedding generation time: {result.embedding_seconds:.4f} seconds")
    st.write(f"Total end-to-end query execution time: {result.total_seconds:.4f} seconds")
    st.write(f"Retrieval time: {result.retrieval_seconds:.4f} seconds")
    st.write(f"Reranking time: {result.rerank_seconds:.4f} seconds")
    server_time = (f"{result.server_seconds:.4f} seconds"
                   if result.server_seconds is not None else "Not reported")
    ru = f"{result.ru:.2f}" if result.ru is not None else "Not reported"
    st.write(f"Total server query execution time: {server_time}")
    st.write(f"RU consumed: {ru}")
    st.write(f"Semantic reranking: {'✓ Applied' if result.reranked else '✗ Not applied'}")
    st.write(f"Found {len(result.rows)} records.")
    st.write(f"Retrieved candidates: {result.retrieved_count}; returned results: {len(result.rows)}")
    st.table(st.session_state.suggested_listings)
    if result.sentence_scores_requested:
        for rank, row in enumerate(result.rows, 1):
            with st.expander(f"Sentence scores: result {rank} ({row['id']})", expanded=False):
                scores = row.get("sentence_scores")
                if scores:
                    for score in scores:
                        st.write(f"Service sentence index: {score['index']}; score: {score['score']}")
                else:
                    st.write("Sentence scores: not returned.")
else:
    st.write("Enter text to get started.")
