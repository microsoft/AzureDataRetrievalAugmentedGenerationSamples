# Semantic search and standalone reranking

> Advanced legacy/manual workflow. Use [README.md](README.md) for automatic
> real embeddings and full pinned MovieLens restoration. Synthetic integration vectors
> below are not the default search dataset.

A Streamlit movie-search sample using Azure Cosmos DB for NoSQL retrieval and
the public GA [`azure-data-ai==1.0.0`](https://pypi.org/project/azure-data-ai/1.0.0/)
`InferenceClient` for semantic reranking. Cosmos DB does retrieval, not inference.

The original UI remains: index selector, search input, reranker checkbox,
**Similarity search**, **Full text ranking**, **Hybrid search**, **Full text search**,
the **all keywords / any keywords** radio, and the results/metrics table.

![Search demo](media/screen-shot.png)

The screenshot shows the original layout. The current app also reports separate
retrieval and reranking durations.

## Legacy manual integration setup: azd backend and local Python

Read **[all prerequisites](infra/azd/README.md#all-prerequisites)** first,
including azd, Azure CLI, PowerShell 7 on every OS, Python/venv/pip,
authentication, subscription permissions, provider registration, network
access, service availability, quotas and ongoing container charges.
Docker and .NET are not required for this standalone Python path. These manual
tests do not call OpenAI, but current azd infrastructure provisions it; its quota
and cost prerequisites still apply.

From this sample directory in PowerShell 7, starting with a clean clone:

```powershell
python -m venv .venv
$py = if ($IsWindows) { './.venv/Scripts/python.exe' } else { './.venv/bin/python' }
& $py -m pip install -r requirements.txt -r requirements-dev.txt
& $py -m pytest -q tests/unit tests/ui
az bicep build --file infra/azd/main.bicep --stdout

$tenant = Read-Host 'Tenant ID'
$subscription = Read-Host 'Subscription ID'
azd auth login --tenant-id $tenant
az login --tenant $tenant
az account set --subscription $subscription
azd init --environment reranker-python-dev
azd env set AZURE_SUBSCRIPTION_ID $subscription
azd env set AZURE_LOCATION uksouth
azd env select reranker-python-dev
# Must print false before the FIRST provision. Choose another unused name otherwise.
az group exists --name rg-reranker-reranker-python-dev --subscription $subscription
azd provision
if ($LASTEXITCODE -ne 0) { throw 'Provisioning or configuration hook failed' }
. ./.local/azd-env.ps1
```

On Linux/macOS use `python3 -m venv .venv` for the first command, still
running the subsequent commands in `pwsh`. Use an environment name unique
in your subscription; replace `reranker-python-dev` consistently if needed.

This creates a dedicated resource group, GUID-named keyless Cosmos and
inference accounts, database `reranker`, and both sample containers at
**400 RU/s each**, with vector and full-text policies. Preprovision persists a
canonical lowercase GUID starting **a-f** for both accounts. It reuses a valid
existing account output and keeps the persisted GUID on reprovision. Other
existing-resource accounts are not referenced. Preserve ignored azd state.
There are no hosted application services. This manual workflow uses `azd provision`
without automatic seeding; the default `azd up` restores the full MovieLens corpus.

The postprovision hook automatically merges the required values into ignored
`.env` and emits ignored `.local/azd-env.ps1`. It preserves unrelated `.env`
bindings, while azd manages the embedding deployment settings. A subprocess cannot change your calling shell:
dot-source as above, especially for live tests or after switching environments.
Existing process settings override Python `.env`. Restart apps after a switch.

Load and run using **only generated backend configuration**:

```powershell
& $py scripts/make-fixtures.py
& $py src/data/data-loader.py `
  --path_to_json_array tests/fixtures/movies.synthetic.json `
  --text_field_name text --vector_field_name embedding --re_embed False `
  --existing-only --max-items 3 --confirm-write --concurrency 1
if ($LASTEXITCODE -ne 0) { throw 'Fixture loading failed' }
# Repeat the loader command to verify stable-ID upserts.
$env:RUN_LIVE_TESTS = '1'
$env:ALLOW_FIXTURE_UPSERT = '1'
& $py -m pytest -q tests/live --ignore=tests/live/test_original_movies.py
Remove-Item Env:RUN_LIVE_TESTS, Env:ALLOW_FIXTURE_UPSERT
& $py -m streamlit run src/app/cosmos-app.py --server.port 8501
```

Allow role/index propagation before live checks. Open `http://localhost:8501`;
try **orbital rescue**, both indexes, full-text search/ranking and reranker
off/on. Synthetic vectors validate integration, not real embedding quality.
See [refresh, switching, inventory and destructive cleanup](infra/azd/README.md).
Do not run `azd down` as a test; leave resources available for inspection.
Failed provisioning can leave paid partial resources. See
[naming preflight and recovery](infra/azd/README.md#naming-preflight-and-failed-provisioning)
before authorizing a replacement name; there is no automatic Azure rollback.

## Alternative quickstart: existing resources, no OpenAI needed

Use full-text retrieval plus optional semantic reranking first. The bundled
original fixtures need neither an OpenAI resource nor an embedding API call.

### 1. Install locally

Prerequisites:

- Python 3.10 or newer. Python 3.11 or 3.12 is a useful starting point.
- Azure CLI, signed in to the intended tenant/subscription.
- An **existing** Cosmos DB for NoSQL account and SQL database.
- Vector and full-text search capabilities available/enabled on that account.
  This sample does not change account capabilities.
- Permission to provision missing sample containers through the Azure control
  plane, or an administrator who can run the setup step.
- A companion inference account in a supported region when reranking is enabled.
  The standalone package is GA; service availability and access can vary.

From this sample directory:

```powershell
python -m venv .venv
$py = ".\.venv\Scripts\python.exe"
& $py -m pip install -r requirements.txt -r requirements-dev.txt
az login
```

On Linux/macOS, use `python3 -m venv .venv`, then
`source .venv/bin/activate` and `python` in place of `& $py`.
Use standard public package sources. No private feed is required.

### 2. Explicitly provision missing containers

Choose an existing database dedicated to the sample. Set these shell variables
privately, using your own values:

```powershell
$subscription = "<subscription-id>"
$resourceGroup = "<existing-resource-group>"
$account = "<existing-cosmos-account>"
$database = "<existing-database>"

& $py src/container_setup.py `
  --subscription $subscription --resource-group $resourceGroup `
  --account $account --database $database --confirm-create
if ($LASTEXITCODE -ne 0) { throw "Container setup failed" }
```

This explicit Azure CLI control-plane step:

- Lists the database's containers and validates existing sample policies first.
- Creates **only** `search_qflat` and `search_diskann` if missing.
- Uses manual **400 RU/s per new container**, not autoscale or a large loader default.
- Uses `/id` partition keys, `/text` English full-text policies/indexes, and
  `/embedding` float32, 1536-dimensional cosine vector policies.
- Uses `quantizedFlat` and `diskANN` vector indexes respectively.
- Reuses compatible existing containers without changing their throughput.
- Fails on incompatible containers. It never deletes or replaces them.
- Does not create/redeploy the Cosmos account or database or assign roles.

Running without `--confirm-create` only inspects policies and reports missing
containers. It does not create them. The Azure CLI must support
`--idx`, `--vector-embeddings` and `--full-text-policy` on
`az cosmosdb sql container create`.

The loader and app **never perform DDL**. Cosmos data-plane permissions alone
must not be assumed to authorize ARM container provisioning.

### 3. Set up inference and permissions

For reranking, run the companion-only setup described in
[infra/README.md](infra/README.md), or reuse a compatible inference account.
That setup references the existing Cosmos account; it must not redeploy it.
Copy the inference endpoint returned by the service. Do not derive or guess it.

```powershell
$location = "<supported-inference-region>"
# Read-only inspection/reuse first:
& $py src/inference_setup.py --subscription $subscription `
  --resource-group $resourceGroup --account $account --location $location
# Only if missing, explicitly authorize companion creation:
& $py src/inference_setup.py --subscription $subscription `
  --resource-group $resourceGroup --account $account --location $location --confirm-create
```

The inference resource uses the same name as the existing Cosmos account.
The infra guide covers provider registration and the separate, optional
`--assign-role` flag. Use that flag **or** the manual role commands below, not
both needlessly. Default execution never creates a resource or assigns a role.

The identity running the app needs separate permissions:

| Operation | Permission and scope |
|---|---|
| Search/read documents | Cosmos DB data-plane role with read/query permissions; the built-in Data Reader can be used for a read-only app |
| Load fixture documents | Cosmos DB Built-in Data Contributor, scoped to the sample database where possible |
| Invoke semantic reranker | Azure RBAC **Semantic Reranker User**, scoped to the companion inference resource |
| Create containers | Appropriate Cosmos control-plane permission, separate from data-plane roles |
| Generate real embeddings (optional) | Cognitive Services OpenAI User on the existing OpenAI resource, or a privately supplied key |

An Azure resource Contributor role does not by itself grant Cosmos document
access. Cosmos document access does not grant inference access.

An administrator can assign Cosmos Data Contributor explicitly:

```powershell
$principalId = "<user-or-managed-identity-object-id>"
$cosmosId = az cosmosdb show --subscription $subscription `
  --resource-group $resourceGroup --name $account --query id -o tsv

az cosmosdb sql role assignment create --subscription $subscription `
  --resource-group $resourceGroup --account-name $account `
  --principal-id $principalId `
  --role-definition-id "$cosmosId/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002" `
  --scope "$cosmosId/dbs/$database"

$inferenceId = "<existing-inference-resource-id>"
az role assignment create --assignee-object-id $principalId `
  --role "Semantic Reranker User" --scope $inferenceId
```

These are explicit administrator actions, not startup operations. Do not run
them when compatible assignments already exist. Allow time for propagation.

### 4. Configure the app

```powershell
Copy-Item .env.template .env
```

Edit the sample-root `.env` privately:

```dotenv
COSMOS_URI=https://YOUR-COSMOS-ACCOUNT.documents.azure.com:443/
COSMOS_DB_DATABASE=YOUR-EXISTING-DATABASE
AZURE_AI_INFERENCE_ENDPOINT=https://YOUR-INFERENCE-ENDPOINT.dbinference.azure.com
```

`DefaultAzureCredential` uses your Azure CLI identity locally and managed
identity on Azure. No Cosmos key is used. Process environment settings override
`.env`. Set `DEMO_LOAD_DOTENV=false` to disable local file loading entirely.
Full-text retrieval with the reranker unchecked does not need an inference endpoint.

### 5. Load the original preembedded fixtures

Materialize the bundled fixture, then explicitly confirm its bounded upserts:

```powershell
& $py scripts/make-fixtures.py
& $py src/data/data-loader.py `
  --path_to_json_array tests/fixtures/movies.synthetic.json `
  --text_field_name text --vector_field_name embedding --re_embed False `
  --existing-only --max-items 3 --confirm-write --concurrency 1
if ($LASTEXITCODE -ne 0) { throw "Fixture load failed" }
```

The generator is fully local and deterministic. The generated JSON contains
three original movie descriptions, stable IDs and actual preembedded arrays.
The loader validates the selected records and both container policies before
writing. Repeating the command upserts the same IDs in both containers.
It reports attempted/succeeded/failed counts **per container** and returns a
nonzero exit code on any failure. Partial success is not rolled back.

`--max-items` selects at most that many input records; output includes both
source and selected counts. It is required, as is `--confirm-write`.
`--existing-only` is accepted for clarity; existing-only behavior is always on.
`--re_embed False` is a real boolean, not a truthy nonempty string.
Retries are bounded. Retryable throttling/service failures can still cause a
nonzero exit; fix the cause and repeat the idempotent command.

The fixture vectors are deterministic unit vectors, **not language embeddings**.
They exercise actual vector indexing/query plumbing, not embedding quality.
Do not use OpenAI query vectors against these fixtures to judge semantic quality.

### 6. Run the original UI

```powershell
& $py -m streamlit run src/app/cosmos-app.py --server.port 8501
```

Open `http://localhost:8501`. Choose either index, enter **orbital rescue**, and
click **Full text search** or **Full text ranking**. Try the reranker checkbox
off and on. Search results retain IDs, titles, text and retrieval scores where
available. Reranked results add `rerank_score`.

Failures are visible and clear stale results. The app never silently treats
unreranked results as a reranking success. An empty retrieval result does not
call inference. Startup does not connect, create containers or load data.
The checkbox controls the next search; displayed metrics describe the last
completed search, not a changed checkbox that has not yet been submitted.

## Run tests

### Offline

```powershell
& $py -m pytest -q tests/unit tests/ui
```

Offline tests prohibit external TCP, UDP and DNS and disable `.env` loading.
Loopback runtime IPC is allowed so Windows asyncio/AppTest can create its
local wake-up socketpair. Azure/service boundaries remain mocked. Tests cover
the standalone request/response contract, invalid indices/scores, duplicate
text, metadata, visible failures, all four UI paths, boolean parsing, schema
validation, bounded retries, partial counts, no-write startup and setup guards.
AppTest executes the page and button callbacks, not just a health endpoint.

### Live, opt-in and fail-loud

First provision, configure and load as above. For azd, dot-source
`. ./.local/azd-env.ps1` and use the live commands in the recommended quickstart;
do not replace generated endpoints with placeholders below.
For the existing-resource alternative, put configuration in process
environment variables for live tests; an enabled suite will not silently skip
missing settings. This avoids accidentally reading a developer `.env`.

```powershell
$env:COSMOS_URI = "<your-private-cosmos-endpoint>"
$env:COSMOS_DB_DATABASE = $database
$env:AZURE_AI_INFERENCE_ENDPOINT = "<your-private-inference-endpoint>"
$env:RUN_LIVE_TESTS = "1"
$env:ALLOW_FIXTURE_UPSERT = "1"
& $py -m pytest -q tests/live/test_data_load.py
& $py -m pytest -q tests/live/test_reranker.py tests/live/test_app_smoke.py
Remove-Item Env:RUN_LIVE_TESTS, Env:ALLOW_FIXTURE_UPSERT
```

Without `RUN_LIVE_TESTS=1`, live tests skip by design. Once enabled, missing
configuration, authentication, fixture files or loaded data fail the suite.
The data-load test explicitly writes only the stable fixture IDs, repeats the
loader, verifies counts and point-readbacks, and leaves the data in place.
The inference test calls the real standalone service. The UI tests execute
full-text/ranking callbacks against both real containers with reranking off/on.

Direct live vector/hybrid tests use the known fixture query vector
`[1, 0, ..., 0]`. They are real Cosmos queries but **not** semantic quality
validation. Real-embedding vector/hybrid UI validation is separate and requires
an actual OpenAI deployment and consistently reembedded data.

## Optional: real semantic embeddings

No OpenAI resource is provisioned by this sample. Configure an existing deployment
which produces 1536-dimensional vectors:

```dotenv
AZURE_OPENAI_ENDPOINT=https://YOUR-OPENAI-RESOURCE.openai.azure.com/
AZURE_OPENAI_EMBEDDING_DEPLOYMENT=YOUR-EMBEDDING-DEPLOYMENT
AZURE_OPENAI_API_VERSION=2024-02-01
```

Prefer Entra authentication with Cognitive Services OpenAI User.
If necessary, set `AZURE_OPENAI_API_KEY` privately. The OpenAI client is created
only when an embedding is requested. Missing configuration produces an actionable
message for **Similarity search** and **Hybrid search**, without blocking full text.

Prepare a local JSON array containing `id`, `title`, and your text field.
Then use the same deployment for document and query embeddings:

```powershell
& $py src/data/data-loader.py --path_to_json_array YOUR-OWN-DATA.json `
  --text_field_name overview --vector_field_name vector --re_embed True `
  --existing-only --max-items 100 --confirm-write --concurrency 1
```

Reembedding is optional; a valid existing vector field can be loaded with
`--re_embed False`. Existing 256-dimensional datasets cannot be loaded directly
into these 1536-dimensional containers. Do not mix embedding models in a container
when evaluating relevance. Keep the synthetic fixtures in a dedicated database.

## Deploy to Azure App Service

See [App Service deployment](infra/app-service.md) for a Linux Python deployment
using managed identity, separate Cosmos/inference roles, server startup, private
app settings and post-deployment verification. Deploy the sample directory,
not the entire repository or a local `.venv`/`.env`.

## Troubleshooting

| Symptom | Check |
|---|---|
| Cosmos 401/403 or visible search error | `az account show`, tenant, Cosmos **data-plane** role, database scope, firewall/private networking |
| Container setup denied | Control-plane permission and selected subscription. Do not retry by changing/deleting the account |
| Container policy mismatch | Wrong database or incompatible existing containers. Setup intentionally refuses replacement |
| Full-text/vector query rejected | Account capabilities, correct container policies, current SDK/CLI, indexing readiness |
| No fixture results | Loader exit status and counts, correct database, point-readbacks, full-text index propagation |
| Reranker denied/unavailable | Inference endpoint, companion resource provisioning, **Semantic Reranker User** scope/propagation, supported region/service access |
| Invalid reranker response | Check the pinned public GA package and service response contract. Do not add silent fallback or guess indices |
| Missing OpenAI config | Use full-text modes or configure the deployment and role; no embedding call is needed for preembedded loading |
| Persistent throttling | Use concurrency 1, a smaller explicit batch, and retry later. No automatic throughput change |
| App starts but requests fail | Test a real search interaction. HTTP health alone does not prove the page or Azure calls succeeded |

Error messages shown in the UI intentionally omit raw service responses and
resource identifiers. Do not publish raw authenticated diagnostics.

Loader failures include `phase`, exception type, error category, HTTP status
when available, and an actionable hint. Upsert output includes up to 20 sanitized
failure details alongside complete per-container counts. No raw exception
messages, service headers, endpoints or tokens are included in these diagnostic
fields. The pinned Cosmos SDK uses **seconds** for `connection_timeout`;
the removed legacy `request_timeout` option used milliseconds. Do not mix them.

## Cleanup: optional and destructive

Do not run cleanup as a test. The fixture data is intentionally left in place.
This explicit command is a **dry run** and makes no Azure calls:

```powershell
& $py src/data/drop-containers.py --subscription $subscription `
  --resource-group $resourceGroup --account $account --database $database `
  --container search_qflat
```

Only if you intend to permanently delete that entire selected container,
including all documents, add
`--confirm-delete "$account/$database/search_qflat"`.
The utility accepts only one of the two sample container names. It never deletes
the database, account or inference resource. Repeat separately for the other
container only with explicit authorization.

## Implementation notes and license

- `src/search_demo.py`: lazy shared clients, retrieval queries, standalone reranking.
- `src/load_data.py`: input validation, bounded retries, truthful loader counts.
- `src/container_setup.py`: explicit control-plane policies and setup only.
- `src/inference_setup.py`: explicit same-name companion setup and optional scoped role assignment.
- `src/cleanup.py`: opt-in exact-target cleanup.
- `src/app/cosmos-app.py`: the Streamlit UI.
- `tests/`: offline, AppTest and opt-in live acceptance checks.

The standalone request uses `query`, `documents`, `topK`, `sort`,
`returnDocuments`. Response `scores` entries use lowercase `index` and `score`.
Original rows are mapped by index, never guessed from duplicate document text.

See the repository [MIT license](../../LICENSE). The small synthetic fixtures and
setup scripts are original sample content under that license.
