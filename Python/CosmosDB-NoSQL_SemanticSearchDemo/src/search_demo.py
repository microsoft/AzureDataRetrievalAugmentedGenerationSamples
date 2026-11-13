"""Shared search seams. Importing this module performs no Azure operations."""

from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
import json
import math
import os
from pathlib import Path
import time

DIMENSIONS = 1536
CONTAINERS = ("search_qflat", "search_diskann")
ROOT = Path(__file__).resolve().parents[1]


class SearchError(RuntimeError):
    """An actionable message safe to show in the UI."""


def load_environment():
    if os.getenv("DEMO_LOAD_DOTENV", "true").lower() == "true":
        from dotenv import load_dotenv
        # Explicit process settings take precedence over local development files.
        load_dotenv(ROOT / ".env", override=False)


@dataclass(frozen=True)
class Settings:
    endpoint: str
    database: str

    @classmethod
    def from_env(cls):
        load_environment()
        endpoint = os.getenv("COSMOS_URI", "").strip()
        database = os.getenv("COSMOS_DB_DATABASE", "").strip()
        if not endpoint.startswith("https://") or not database:
            raise SearchError("Set COSMOS_URI (https://...) and COSMOS_DB_DATABASE. "
                              "Provision the sample containers before loading or searching.")
        return cls(endpoint, database)


@lru_cache(maxsize=1)
def get_credential():
    from azure.identity import DefaultAzureCredential
    return DefaultAzureCredential()


@lru_cache(maxsize=4)
def get_cosmos_client(endpoint):
    from azure.cosmos import CosmosClient
    # Application retry loops are bounded too. No automatic write retries.
    # Cosmos 4.14: connection_timeout is seconds; legacy request_timeout is milliseconds.
    return CosmosClient(endpoint, credential=get_credential(),
                        retry_total=3, retry_write=0,
                        connection_timeout=30)


def error_details(exc):
    """Useful diagnostic fields without raw messages, URLs, headers or tokens."""
    name = type(exc).__name__
    status = getattr(exc, "status_code", None)
    status = status if isinstance(status, int) else None
    if "Timeout" in name or isinstance(exc, TimeoutError):
        category = "timeout"
        hint = "Check network latency and SDK timeout units. Cosmos connection_timeout uses seconds."
    elif status == 401 or "Authentication" in name or "Credential" in name:
        category = "authentication"
        hint = "Check Azure CLI/managed identity credentials and the selected tenant."
    elif status == 403:
        category = "authorization"
        hint = "Check the required data-plane role and scope, propagation and network restrictions."
    elif status == 429:
        category = "throttling"
        hint = "Use lower concurrency or a smaller batch and retry later; throughput is not changed."
    elif status == 404:
        category = "not-found"
        hint = "Check the configured database and explicitly provisioned sample containers."
    elif isinstance(exc, ValueError):
        category = "validation"
        hint = "Check selected document schema, dimensions and container policies."
    elif "Connection" in name or "ServiceRequest" in name or "ServiceResponse" in name:
        category = "network"
        hint = "Check DNS, firewall/private endpoint access and service availability."
    else:
        category = "service" if status else "unexpected"
        hint = "Use the exception type and phase to isolate the failing operation."
    return {"category": category, "exception_type": name, "status_code": status, "hint": hint}


def get_containers(settings):
    database = get_cosmos_client(settings.endpoint).get_database_client(settings.database)
    return {name: database.get_container_client(name) for name in CONTAINERS}


def get_container(name):
    if name not in CONTAINERS:
        raise SearchError("Select a supported sample container.")
    return get_containers(Settings.from_env())[name]


@lru_cache(maxsize=1)
def get_inference_client():
    load_environment()
    endpoint = os.getenv("AZURE_AI_INFERENCE_ENDPOINT", "").strip()
    if not endpoint.startswith("https://"):
        raise SearchError("Set AZURE_AI_INFERENCE_ENDPOINT to the companion inference endpoint "
                          "and grant Semantic Reranker User to your identity.")
    from azure.data.ai import InferenceClient
    return InferenceClient(endpoint=endpoint, credential=get_credential(),
                           retry_total=3, connection_timeout=10, read_timeout=60)


@lru_cache(maxsize=1)
def get_embedding_client():
    load_environment()
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "").strip()
    deployment = os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "").strip()
    if not endpoint or not deployment:
        raise SearchError("Vector and hybrid search require AZURE_OPENAI_ENDPOINT and "
                          "AZURE_OPENAI_EMBEDDING_DEPLOYMENT. Use full text search/ranking "
                          "without OpenAI, or configure a 1536-dimensional embedding deployment.")
    from openai import AzureOpenAI
    from azure.identity import get_bearer_token_provider
    options = {"azure_endpoint": endpoint,
               "api_version": os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-01"),
               "max_retries": 2, "timeout": 30.0}
    key = os.getenv("AZURE_OPENAI_API_KEY")
    if key and os.getenv("AZURE_OPENAI_AUTH_MODE") != "entra":
        options["api_key"] = key
    else:
        options["azure_ad_token_provider"] = get_bearer_token_provider(
            get_credential(), "https://cognitiveservices.azure.com/.default")
    return AzureOpenAI(**options)


def validate_vector(value):
    if not isinstance(value, list) or len(value) != DIMENSIONS:
        raise ValueError("embedding must be a list of 1536 finite numbers.")
    if any(isinstance(x, bool) or not isinstance(x, (int, float))
           or not math.isfinite(x) or abs(x) > 3.4028235e38 for x in value):
        raise ValueError("embedding must contain finite float32-compatible numbers.")
    if not any(value):
        raise ValueError("embedding must be nonzero for cosine distance.")
    return value


def embed_text(text):
    client = get_embedding_client()
    try:
        response = client.embeddings.create(
            input=text, model=os.environ["AZURE_OPENAI_EMBEDDING_DEPLOYMENT"],
            dimensions=DIMENSIONS)
        if len(response.data) != 1 or response.data[0].index != 0:
            raise ValueError("Embedding service returned an unexpected response.")
        return validate_vector(response.data[0].embedding)
    except Exception as exc:
        raise SearchError("Embedding request failed. Check the deployment, 1536 dimensions, "
                          "network access and OpenAI credentials/role.") from exc


@dataclass(frozen=True)
class RerankOptions:
    document_format: str = "text"
    target_paths: tuple[str, ...] = ("title", "text")
    top_k: int = 10
    return_sentence_scores: bool = False

    def validate(self):
        if self.document_format not in ("text", "json"):
            raise ValueError("Select text or json document format.")
        if type(self.top_k) is not int or not 1 <= self.top_k <= 10:
            raise ValueError("Rerank result limit must be an integer between 1 and 10.")
        if type(self.return_sentence_scores) is not bool:
            raise ValueError("Sentence-score diagnostics must be on or off.")
        if self.document_format == "json" and self.target_paths not in (
                ("title",), ("text",), ("title", "text")):
            raise ValueError("JSON targeting must select title, text, or title and text.")


def sentence_scores(entry):
    """Keep service indices, never infer sentence text or JSON field alignment."""
    values = entry.get("sentenceScores")
    if values is None:
        return None
    if not isinstance(values, list):
        raise SearchError("Invalid reranker response: expected sentence score objects.")
    seen, result = set(), []
    for value in values:
        if not isinstance(value, Mapping):
            raise SearchError("Invalid reranker response: expected sentence score objects.")
        index, score = value.get("index"), value.get("score")
        if (type(index) is not int or index < 0 or index in seen
                or isinstance(score, bool) or not isinstance(score, (int, float))
                or not math.isfinite(score)):
            raise SearchError("Invalid reranker response: invalid sentence index/score.")
        seen.add(index)
        result.append({"index": index, "score": float(score)})
    return result


def rerank(client, query, rows, options=None):
    options = options or RerankOptions()
    options.validate()
    if not rows:
        return []
    if len(rows) > 10:
        raise SearchError("Reranking accepts at most 10 retrieved candidates.")
    paths = options.target_paths if options.document_format == "json" else ("text",)
    if any(not isinstance(row.get(path), str) or not row[path].strip()
           for row in rows for path in paths):
        raise SearchError("Reranking requires nonempty selected fields on every retrieved document.")
    # Construct a new whitelist projection, never serialize a whole Cosmos document.
    documents = ([json.dumps({path: row[path] for path in paths}, ensure_ascii=True)
                  for row in rows] if options.document_format == "json"
                 else [row["text"] for row in rows])
    expected = min(options.top_k, len(rows))
    payload = {
        "query": query, "documents": documents, "topK": expected,
        "sort": True, "returnDocuments": False,
    }
    if options.document_format == "json":
        payload.update(documentType="json", targetPaths=",".join(paths))
    if options.return_sentence_scores:
        payload["returnSentenceScore"] = True
    try:
        response = client.semantic_rerank(payload)
    except Exception as exc:
        raise SearchError("Reranking failed. No results are labelled reranked. Check the "
                          "inference endpoint, Semantic Reranker User role, propagation "
                          "and service availability.") from exc
    scores = response.get("scores") if isinstance(response, Mapping) else None
    if not isinstance(scores, list) or len(scores) != expected:
        raise SearchError("Invalid reranker response: unexpected result count.")
    seen, result = set(), []
    for entry in scores:
        if not isinstance(entry, Mapping):
            raise SearchError("Invalid reranker response: expected score objects.")
        index, score = entry.get("index"), entry.get("score")
        if (type(index) is not int or not 0 <= index < len(rows) or index in seen
                or isinstance(score, bool) or not isinstance(score, (int, float))
                or not math.isfinite(score)):
            raise SearchError("Invalid reranker response: index/score is missing, invalid or duplicate.")
        seen.add(index)
        # Index mapping is essential: different records can have identical text.
        row = {**rows[index], "rerank_score": float(score),
               "retrieval_index": index, "retrieval_rank": index + 1}
        if options.return_sentence_scores:
            row["sentence_scores"] = sentence_scores(entry)
        result.append(row)
    return sorted(result, key=lambda row: row["rerank_score"], reverse=True)


def build_query(mode, text, search_type="all keywords", vector=None):
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Enter a nonempty search query.")
    if len(text) > 2000:
        raise ValueError("Search query must not exceed 2000 characters.")
    select = "SELECT TOP 10 l.id, l.title, l.text"
    parameters = []
    if mode in ("vector", "hybrid"):
        validate_vector(vector)
        parameters.append({"name": "@vector", "value": vector})
    if mode == "vector":
        return (select + ", VectorDistance(l.embedding, @vector) AS SimilarityScore "
                "FROM l ORDER BY VectorDistance(l.embedding, @vector)", parameters)
    if mode == "fulltext":
        if search_type not in ("all keywords", "any keywords"):
            raise ValueError("Select all keywords or any keywords.")
        function = "FullTextContainsAll" if search_type == "all keywords" else "FullTextContainsAny"
        for i, word in enumerate(text.split()):
            parameters.append({"name": f"@word{i}", "value": word})
        words = ", ".join(p["name"] for p in parameters)
        return f"{select} FROM l WHERE {function}(l.text, {words})", parameters
    # FullTextScore currently requires literal search terms in ORDER BY RANK.
    # JSON encoding escapes quotes, backslashes and control characters safely.
    terms = ", ".join(json.dumps(word, ensure_ascii=True) for word in text.split())
    score = f"FullTextScore(l.text, {terms})"
    if mode == "ranking":
        return f"{select} FROM l ORDER BY RANK {score}", parameters
    if mode == "hybrid":
        return (f"{select} FROM l ORDER BY RANK RRF({score}, "
                "VectorDistance(l.embedding, @vector))", parameters)
    raise ValueError("Unknown search mode.")


@dataclass
class SearchResult:
    rows: list
    query: str
    embedding_seconds: float
    retrieval_seconds: float
    rerank_seconds: float
    total_seconds: float
    ru: float | None
    server_seconds: float | None
    reranked: bool
    retrieved_count: int = 0
    sentence_scores_requested: bool = False


def search(container, mode, text, use_reranker=False, inference_client=None,
           embedder=None, search_type="all keywords", rerank_options=None):
    start = time.perf_counter()
    options = (rerank_options or RerankOptions()) if use_reranker else RerankOptions()
    if use_reranker:
        options.validate()
    embedding_seconds = 0.0
    vector = None
    if mode in ("vector", "hybrid"):
        vector = (embedder or embed_text)(text)
        embedding_seconds = time.perf_counter() - start
    query, parameters = build_query(mode, text, search_type, vector)
    ru, server_seconds = None, None

    def metrics(headers, _body):
        nonlocal ru, server_seconds
        if "x-ms-request-charge" in headers:
            ru = (ru or 0.0) + float(headers["x-ms-request-charge"])
        for part in headers.get("x-ms-documentdb-query-metrics", "").split(";"):
            key, _, value = part.partition("=")
            if key.endswith("totalExecutionTimeInMs"):
                try:
                    server_seconds = (server_seconds or 0.0) + float(value) / 1000
                except ValueError:
                    pass

    retrieval_start = time.perf_counter()
    try:
        rows = list(container.query_items(
            query, parameters=parameters, enable_cross_partition_query=True,
            populate_query_metrics=True, response_hook=metrics))
    except Exception as exc:
        raise SearchError("Search failed. Check Cosmos data-plane permissions, container "
                          "setup, indexing readiness and network access.") from exc
    retrieval_seconds = time.perf_counter() - retrieval_start
    retrieved_count = len(rows)
    rerank_seconds, applied = 0.0, False
    if use_reranker and rows:
        rerank_start = time.perf_counter()
        rows = rerank(inference_client or get_inference_client(), text, rows, options)
        rerank_seconds, applied = time.perf_counter() - rerank_start, True
    return SearchResult(rows, query, embedding_seconds, retrieval_seconds, rerank_seconds,
                        time.perf_counter() - start, ru, server_seconds, applied,
                        retrieved_count, applied and options.return_sentence_scores)
