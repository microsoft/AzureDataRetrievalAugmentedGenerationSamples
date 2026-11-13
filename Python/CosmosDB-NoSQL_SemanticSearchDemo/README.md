# Semantic search and standalone reranking

A local Streamlit movie-search sample using Azure Cosmos DB for NoSQL,
Azure OpenAI embeddings and the public GA `azure-data-ai==1.0.0` inference client.
The existing layout and search controls are preserved, with a collapsed
Advanced reranking section. See the [search guide](SEARCH_GUIDE.md) for manual
startup, feature walkthroughs, JSON targeting, result limits and sentence diagnostics.

## Prerequisites

Install Git, Azure CLI, azd (baseline 1.25.6), PowerShell 7 on every OS,
Python 3.10+ with venv/pip, and trusted public package/Azure network access.
Standalone Python needs neither .NET nor Docker.

Use the same Entra identity and subscription for `az login` and `azd auth login`.
You need resource creation and scoped role-assignment permissions, registered
DocumentDB/InferenceService/CognitiveServices providers, inference service access,
Cosmos quota, and available OpenAI model quota.

Default embeddings: UKSouth, `text-embedding-3-small`, version `1`,
GlobalStandard capacity `30`, explicitly requested 1536 dimensions.
GlobalStandard can process globally, not exclusively in UKSouth.
This is pay-per-token usage, not provisioned OpenAI throughput. Budget for
two continuously billed 400 RU/s containers, storage, inference and embedding
tokens. See [all prerequisites](infra/azd/README.md#all-prerequisites).

## Deploy and run

From this directory:

```powershell
azd up
pwsh ./scripts/start.ps1
```

Choose a unique environment name, subscription and supported Cosmos/inference
region. Keep ignored `.azure/` state. Use different environments for the standalone
and combined projects. Tools and login are prerequisites, not installed by hooks.
No prior `azd init` or `azd env new` is required. Explicit environment,
subscription and location can be passed directly as `azd up` flags.

`preup` creates `.venv`, installs requirements, persists/reuses the GUID and
resets inference creation to `false`. This bootstrap does not authenticate or
call Azure. The service-free workflow then runs native `azd provision`, not
package/deploy steps. Mandatory `preprovision` uses azd's resolved subscription
and location for the authenticated inference GET; only HTTP 404 authorizes
creation. No hook guesses unresolved flags or falls back to the CLI's default
subscription.
`postprovision` only generates private `.env`
and `.local/azd-env.ps1`. `postup` restores all **4,489 MovieLens source rows**
from the [pinned original file in the user's fork](https://github.com/TheovanKraay/AzureDataRetrievalAugmentedGenerationSamples/blob/7fd162fc633617857f8b8ed2c5b2b92d4d8ef0b6/DataSet/Movies/MovieLens-4489-256D.json).
It downloads only to ignored `.local/movielens/` and enforces 48,244,182 raw bytes,
SHA256 `5f43a3b0815b80b85c647b38d3d86c320aaf0c0937a79561fe643156e62c6295`,
schema and exact row count. A CRLF checkout is not accepted as the raw source.
The source repository retains its Microsoft MIT attribution.

Source `overview` maps to `text`. Metadata and original ID are retained in
`source_metadata` and `source_movie_id`. Source 256-dimensional vectors are
discarded, never used with the 1536-dimensional containers. Embeddings use only
overview text and the deployed model, with validated indexes, finite values and
dimensions. Source and embedding provenance are stored with each record.
IDs are `movielens-4489-v1-<one-based padded row index>-<original movie ID>`.
There are 4,486 unique original IDs; all 4,489 rows are preserved, not deduplicated.
Only allowlisted title/text fields can be sent for reranking.

The loader preflights ownership across all targets before writes, then verifies
every expected ID, source content, provenance and vector by exact readback.
Only after ALL targets pass may the hook's `--cleanup-original-fixtures` flag
delete the exact ten unchanged `original-movies-v1-` fixture IDs per target with
matching full source data, provenance, ownership and conditional etags.
Changed or foreign records cause an explicit error and are never overwritten
or deleted. The tiny fixture is smoke/offline data only, not the default.

Repeat `azd up` to reuse cached batches and skip unchanged validated records.
**The first full load can take time.** Downloading the corpus, generating real
embeddings, writing the targets and verifying every source row depend on service
latency, throttling and role propagation. No fixed completion time is promised.
Watch embedding-batch progress and per-container preflight, write and readback
progress. Provisioning success alone does not establish a complete load; wait
for the seed hook to succeed.

Missing owned records are repaired. Cache entries include source/content and
deployment/model/version/dimensions provenance plus vector hashes. Corruption
fails explicitly; remove only the named bad entry to regenerate it.
Bounded 403 propagation and 429/5xx retries do not hide the original failure.
Each invocation writes a private receipt under `.local/movielens/`, including
verified counts per container, generated/reused embeddings and removed fixtures.
Keep the ignored cache when resuming. Receipts use unique
`receipt-<unique-id>.json` filenames, so later runs preserve earlier evidence.
Inspect receipt status, verified/skipped/written counts, page counts and phase
timings rather than assuming an interrupted run completed. Keep receipts private.
`azd provision` intentionally does not seed. A failed deployment/seed is not a
success and may leave paid resources; fix the error and retry. Never test with
`azd down`.

The foreground launcher loads generated config automatically and serves
<http://127.0.0.1:8501>. `-PythonPort` selects a different port.
Busy ports fail without stopping existing listeners. Ctrl+C stops only its
owned child process. Launching performs no data writes.

Try **Woody Buzz**, **fishing buddies**, or **toys learning to share a child's affection**.
Exercise both indexes, all four search buttons, full-text all/any, and reranking
off/on. Query and seed embeddings use the same deployed model.
The home screen describes the source corpus, not live contents of a custom
database. The search limit remains 10 candidates, not 10 source records.

To resume only the data step against already configured resources:

```powershell
. ./.local/azd-env.ps1
& ./.venv/Scripts/python.exe src/seed_movies.py --confirm-write --cleanup-original-fixtures
```

On non-Windows use `./.venv/bin/python`. Default embedding batches contain at
most 32 rows; `--batch-size` accepts 1-64. Optional `--source-file <path>` still
enforces exact production bytes/hash/schema/count. This never provisions.
Arbitrary CLI seeds require `--confirm-write`; cleanup is separately explicit.
For combined-root restoration use the root hook or add `--include-dotnet`.

## Configuration and verification

Before `azd up`, `azd env set` can configure `AZURE_OPENAI_LOCATION` (uksouth),
`EMBEDDING_MODEL` (text-embedding-3-small), `EMBEDDING_VERSION` (1),
`EMBEDDING_DEPLOYMENT` (text-embedding-3-small), `EMBEDDING_SKU` (GlobalStandard),
and `EMBEDDING_CAPACITY` (30). `text-embedding-3-large` also uses 1536 dimensions.
Check model/version/SKU regional availability and quota first. No automatic
region fallback. Standard/DataZoneStandard are options only where supported.

```powershell
. ./.local/azd-env.ps1
$py = if ($IsWindows) { './.venv/Scripts/python.exe' } else { './.venv/bin/python' }
& $py -m pytest -q tests/unit tests/ui
$env:RUN_LIVE_TESTS = '1'
& $py -m pytest -q tests/live/test_original_movies.py
Remove-Item Env:RUN_LIVE_TESTS
```

The live matrix uses the actual embedder, both indexes, all modes and rerank
toggles. It is not a browser/UI test. Allow index propagation before checking.
The [advanced manual guide](README.manual.md) retains synthetic offline and
optional integration fixtures, existing-resource setup and browser checks.

For an actual browser matrix, leave the launcher running and use another terminal:

```powershell
& $py -m pip install -r requirements-browser.txt
& $py -m playwright install chromium
$env:RUN_LIVE_TESTS = '1'
& $py scripts/verify_browser.py
Remove-Item Env:RUN_LIVE_TESTS
```

The browser script tests all modes and toggles against the already-running app,
prints each passing case and stores screenshots only under
`.local/validation/movielens/`. It does not manage app processes.
Add `--matrix advanced` to rerun only advanced cases, or `--matrix baseline`
for only the original cases. The default runs both.
