# Python search guide

This guide covers manual local startup and the code behind each search control.
Use [README.md](README.md) for prerequisites and the short quickstart.
[README.manual.md](README.manual.md) is a separate legacy existing-resource and
synthetic-fixture workflow, not a required step in the default deployment.

## Deploy once, then start locally

Deployment stays **`azd up`**. For the combined repository, run it from the
repository root. For standalone Python, run it from this Python sample directory.
Do not deploy both projects into the same environment.

`azd up` installs dependencies, provisions the backend, generates local config,
and restores all 4,489 MovieLens source rows with real Azure OpenAI embeddings.
`azd provision` alone does not seed. No new resources are needed for advanced
reranking, and neither application startup nor searching provisions or writes data.

The normal foreground launcher is `pwsh ./scripts/start.ps1`, run from the
directory where you deployed. In the combined repository it starts both apps.
The following is an alternative when you want to start just Streamlit manually.
Stop your existing owned launcher first so it releases port 8501.

### Manual startup in PowerShell 7

Start in this **Python directory**. In the combined repository, that means
`Set-Location ./python` from the repository root.

```powershell
# azd up normally already created this venv.
# Only if .venv is missing:
python -m venv .venv

$py = if ($IsWindows) { './.venv/Scripts/python.exe' } else { './.venv/bin/python' }
# Needed after a fresh manual venv or a dependency-file change:
& $py -m pip install -r requirements.txt -r requirements-dev.txt

# Generated for this Python sample by azd up:
. ./.local/azd-env.ps1
& $py -m streamlit run src/app/cosmos-app.py `
  --server.address 127.0.0.1 --server.port 8501 --server.headless true
```

On macOS/Linux, use `python3 -m venv .venv` if `python` is not installed.
The explicit `$py` interpreter avoids dependence on activation or global pip.
Alternatively, on Windows activate with `. ./.venv/Scripts/Activate.ps1` and use
`python -m streamlit run src/app/cosmos-app.py --server.address 127.0.0.1 --server.port 8501`.

From the **combined repository root**, the equivalent final steps are:

```powershell
. ./.local/azd-env.ps1
$py = if ($IsWindows) { './python/.venv/Scripts/python.exe' } else { './python/.venv/bin/python' }
& $py -m streamlit run python/src/app/cosmos-app.py `
  --server.address 127.0.0.1 --server.port 8501 --server.headless true
```

Open <http://127.0.0.1:8501>. Ctrl+C stops this manual process. Choose another
`--server.port` if occupied; do not kill an unrelated listener.

### Environment, authentication, and restart

Dot-sourcing the generated script sets variables in the current PowerShell
process. Child processes inherit those values. It can replace values you set
earlier, so intentional temporary overrides belong **after** dot-sourcing.

[`load_environment`](src/search_demo.py) loads this sample's `.env` with
`override=False`: existing process variables take precedence, independent of
the working directory. `DEMO_LOAD_DOTENV=false` disables that optional file load.
The .NET app does not load this Python `.env`.

[`Settings.from_env`, `get_credential`, and the cached client functions](src/search_demo.py)
use `COSMOS_URI`, `COSMOS_DB_DATABASE`, `AZURE_AI_INFERENCE_ENDPOINT`,
`AZURE_OPENAI_ENDPOINT`, and `AZURE_OPENAI_EMBEDDING_DEPLOYMENT`.
Generated configuration is keyless. Local `DefaultAzureCredential` can use
Azure CLI sign-in; sign into the intended tenant and subscription. Cosmos,
inference, and OpenAI need their respective data-plane roles. The reranker role
is Semantic Reranker User. Never fix authorization by adding account keys.

Cached clients and credentials survive Streamlit reruns. After changing
environment or identity, stop the process and start it again from the corrected
shell. A browser refresh alone does not reset those clients. Follow the README
environment-switching procedure before restarting when changing azd environments.
Do not print tokens, commit generated configuration, or copy endpoints into code.

## Dataset shown on the home screen

The main area keeps a compact **Default source corpus: MovieLens** summary above results,
including after a search or an error. It describes all 4,489 source rows
in the [pinned original MovieLens file](https://github.com/TheovanKraay/AzureDataRetrievalAugmentedGenerationSamples/blob/7fd162fc633617857f8b8ed2c5b2b92d4d8ef0b6/DataSet/Movies/MovieLens-4489-256D.json).
The ten-row original-text fixture is smoke/offline test data, not the default.
There is no preview table or live dataset inspection.

Default `azd up` seeds those movies with real embeddings into the sample
containers. The summary is not evidence of what an arbitrary configured
container contains. With custom data, use searches suited to your documents.
The database label comes from local configuration; the selected container
label follows the Index control. Displaying these labels does not connect to
Cosmos DB or validate container contents.

Try `Woody Buzz` or `fishing buddies` with Full text search, or
`toys learning to share a child's affection` with Similarity or Hybrid search.
These examples describe Toy Story and Grumpier Old Men, not guaranteed results for custom data.
Source movie IDs are not unique: row-indexed IDs preserve every source row.
Read [the restoration and resume contract](README.md#deploy-and-run) for checksum,
metadata, cache, full readback and conditional legacy-fixture cleanup details.

## Follow a request through the code

[`run_search`](src/app/cosmos-app.py) clears stale success before calling
[`search`](src/search_demo.py). Search builds a query, retrieves candidates, and
optionally reranks them. The UI keeps the original index selector, four buttons,
all/any radio, metadata table, and timing displays.

The two index choices map to `search_qflat` and `search_diskann`. Default `azd up`
seeds the same full source corpus into both; custom contents can differ.
Retrieval projects `id`, `title`, `text`, and vector
distance where applicable, not embeddings or Cosmos system properties.

### Embeddings and vector similarity

The Similarity search button selects `mode="vector"`.
[`embed_text`](src/search_demo.py) calls the **Azure OpenAI embeddings API** using
the configured deployment. It explicitly requests 1536 dimensions and
[`validate_vector`](src/search_demo.py) checks length, finite float32-compatible
numbers, and nonzero content.

[`build_query`](src/search_demo.py) supplies `@vector` as a parameter and orders
`SELECT TOP 10` by `VectorDistance(l.embedding, @vector)`. Lower distance is better.
The displayed `SimilarityScore` is this distance, not a reranker score.
The query model must match the dataset's embedding model and dimensions.
Changing a deployment name alone does not regenerate stored embeddings.

### Full-text all and any

The Full text search button selects `mode="fulltext"`. `build_query` splits the
input into whitespace-separated keywords and passes them as parameters to
`FullTextContainsAll` or `FullTextContainsAny` on `l.text`.

All means every supplied keyword must match. It is **not** natural-language
query rewriting. A sentence containing extra words may match fewer documents
than a short keyword query. Try `Woody Buzz`, then compare all/any.
Boolean filtering has no relevance-order guarantee and needs no embedding call.
Title is not part of this retrieval filter.

### Full-text ranking

Full text ranking selects `mode="ranking"` and uses
`ORDER BY RANK FullTextScore(l.text, ...)`. Each keyword is a separate argument.
JSON string encoding safely escapes the literal terms required by this query
form. This ranks candidates rather than applying the all/any Boolean filter.
The sample does not project a numeric FullTextScore into the result table.
No Azure OpenAI call is needed.

### Hybrid RRF

Hybrid search selects `mode="hybrid"`, embeds the input, and uses
`ORDER BY RANK RRF(FullTextScore(...), VectorDistance(...))`.
RRF combines the lexical and vector rankings inside Cosmos. It is not an
arithmetic average of the two raw scores. The sample does not project an RRF
score. Both hybrid and plain vector search use the same embedding helper.

### Reranking off and on

With Use Semantic Reranker off, `search` returns retrieval results directly.
Advanced options are disabled and ignored, and no inference client is resolved.

With it on, [`rerank`](src/search_demo.py) sends the bounded candidate list to
**`azure.data.ai.InferenceClient.semantic_rerank`**. This is the standalone
Azure Data AI service, not Azure OpenAI embeddings and not a Cosmos container
method. Defaults are unchanged: plain description strings, all candidates
reranked, sorted results, and no sentence diagnostics. No model or batch picker
is added. Reranking can reorder or reduce candidates, never retrieve new documents.

The response is mapped by its zero-based `index` into the original candidates,
not by returned text. Duplicate descriptions remain distinct by ID and metadata.
`retrieval_index` is zero-based; `retrieval_rank` is one-based. The original
retrieval score is retained. `rerank_score` is separate and higher is better.
The service may include a `document` even with `returnDocuments=false`; the app
ignores it and keeps the original retrieved document.

### Advanced JSON targeting, top-K, and diagnostics

Expand **Advanced reranking**, after enabling the reranker:

| Control | Default | Meaning |
| --- | --- | --- |
| Document format | `text` | Plain `text` description, or opt-in `json` |
| JSON fields | Title and Description | `title`, `text`, or `title,text` |
| Rerank result limit | 10 | Return at most this many of the retrieved candidates |
| Sentence-score diagnostics | Off | Request optional service sentence indices/scores |

[`RerankOptions.validate`](src/search_demo.py) enforces the whitelist and integer
limit 1 through 10 on the server, not only in widgets. JSON mode builds a new
object per candidate containing **only** selected fields, encodes it with
`json.dumps`, and sets `documentType="json"` and comma-separated `targetPaths`.
The public GA `azure-data-ai==1.0.0` client accepts this raw dictionary directly.
Keep `targetPaths` a string in this dictionary, not the list accepted by the
typed request model's `target_paths` constructor. The application does not read
or mutate that typed property before serialization.
Description is the UI label for the actual `text` field. Unselected fields,
embeddings, IDs, and system properties are not sent for inference.
Changing JSON targets affects reranking only, not the Cosmos retrieval query.

The candidate cap stays 10. The request's `topK` is bounded to available
candidates. Exactly `min(requested limit, available candidates)` results must
come back. Zero candidates bypass inference. The UI distinguishes retrieved
candidates from returned results, so top-K is not mistaken for a retrieval limit.

When selected, the payload includes `returnSentenceScore=true`.
[`sentence_scores`](src/search_demo.py) validates numeric service indices and
finite scores. Expand each result's Sentence scores detail to see them.
Indices are service-defined: the app does **not** split or highlight original
text or infer which JSON field an index belongs to. Missing or empty optional
diagnostics display **not returned**. They are not an error and not fabricated
zeros. Unrequested diagnostics are not displayed. Model/version/token metadata
may be returned by the SDK but is not surfaced in this bounded UI.

Malformed score cardinality, duplicate/out-of-range document indices, missing or
nonfinite scores, and malformed requested sentence diagnostics fail closed.
There is no successful-looking fallback to retrieval after a reranker error.

### Exception diagnostics and privacy

The UI logs each failed search once with Python's standard `logging` exception
traceback in the developer-owned Streamlit terminal. Embedding, retrieval and
reranking wrappers retain the original exception as `__cause__` using
`raise ... from exc`. Only the sample's deliberately safe `SearchError` messages
are shown in the browser. Other exceptions, including SDK `ValueError`s, receive
a fixed friendly message. Failed searches clear previous results and timings;
table construction must succeed before a new result is saved.

Loader and setup CLI failure summaries keep fixed guidance and, where available,
the existing sanitized `error_details()` fields (category, exception type, integer
HTTP status and hint), never arbitrary exception text. The original exception
and traceback are logged to the developer terminal instead. Legacy loader write
failures remain failed counts with a nonzero CLI exit, not successful writes.
The MovieLens loader rethrows the original first failure after its pending batch
settles and logs additional batch failures. Receipt/screenshot failures retain
their own local diagnostics without replacing the original operation failure.
CLI subprocess wrappers chain `CalledProcessError`, retaining exit code, command
and captured stdout/stderr on the cause for local debugging.
The azd configuration and naming helpers also log nonempty failed-command
stderr/stdout as labeled sensitive local details alongside the boundary traceback.
Identical text in both streams is logged once, ignoring surrounding whitespace.
Successful command output, including environment values, is not logged.

**Treat terminal stderr/logs and ignored `.local/` receipts/screenshots as private.**
Original exception chains may contain sensitive SDK details, URLs, credentials,
query/document content or local paths. Never commit or share raw logs, receipts
or screenshots, and do not route these logs to a browser or public collector.
If saving diagnostics, use ignored `.local/` only; redact and review any excerpt
before sharing. No SDK HTTP/body logging is enabled by these changes.

Intentional fallbacks remain narrow: malformed optional server timing is ignored,
malformed retry-delay headers use the existing bounded backoff, and an explicit
point-read not-found response represents absence. These do not convert failed
searches or writes into success. Retry policies and limits are unchanged.

## Costs, data, and troubleshooting

Cosmos RU and server metrics come from retrieval response hooks; all pages are
accumulated. Embedding time, retrieval time, reranking time, and total time are
separate. RU is not a token count or the total price of a search. Azure OpenAI
embedding tokens and inference usage are separate service costs. Missing Cosmos
metrics are shown as not reported, not zero.

[`seed_movies.py`](src/seed_movies.py) restores the pinned full MovieLens corpus
and records source/embedding provenance with stable `movielens-4489-v1-` IDs.
[`movies.original.json`](sample-data/movies.original.json) is only the small
smoke fixture and exact migration-cleanup reference, never the default corpus.
Offline synthetic vectors test contracts, not semantic quality.

| Symptom | Check |
| --- | --- |
| Fewer than K results | Candidate count, dataset size, keyword all filtering, index propagation. K cannot create candidates. |
| No candidates | Try short matching keywords or another mode/index. No inference call is made. |
| Missing sentence scores or model metadata | Optional service output is not guaranteed. This UI displays only requested sentence diagnostics. |
| Embedding error | Deployment, Entra role, network, matching 1536-dimensional model. Full-text modes isolate retrieval without OpenAI. |
| Reranker 401/403 | Identity/tenant, returned inference endpoint, Semantic Reranker User role and propagation. Restart after correcting settings/auth. |
| Cosmos auth/config failure | Generated environment, intended existing database/containers, Cosmos data role, network access. Searching never repairs resources. |
| Reranker malformed response | Treat as failure. Keep private diagnostics locally; do not replace scores or silently return retrieval as reranked. |
| Old endpoint still used | Stop Streamlit, reload the intended generated script in a clean shell, restart. Cached clients do not reset on browser refresh. |

## Verification map

From this Python directory, with `$py` set as above:

```powershell
& $py -m pytest -q tests/unit tests/ui
# Only against the azd-up original dataset, with generated configuration loaded:
$env:RUN_LIVE_TESTS = '1'
& $py -m pytest -q tests/live/test_original_movies.py
# Separate terminal, while the app is already running:
& $py -m pip install -r requirements-browser.txt
& $py -m playwright install chromium
& $py scripts/verify_browser.py
Remove-Item Env:RUN_LIVE_TESTS
```

For the combined running apps, add `--include-dotnet` to the browser command.
To rerun only advanced cases, use `& $py scripts/verify_browser.py --matrix advanced`
(also add `--include-dotnet` for both apps). `--matrix baseline` runs only the
original cases; the default `--matrix all` runs both. The live opt-in is still required.
[`test_advanced_reranking.py`](tests/unit/test_advanced_reranking.py) checks
whitelisting, SDK responses, subsets, validation, and optional diagnostics.
[`test_app.py`](tests/ui/test_app.py) uses offline Streamlit AppTest.
[`test_original_movies.py`](tests/live/test_original_movies.py) and
[`verify_browser.py`](scripts/verify_browser.py) cover real advanced cases and
reranker-off behavior. Browser screenshots stay in ignored `.local/`.
Live tests and browser checks incur service usage but do not seed data.
