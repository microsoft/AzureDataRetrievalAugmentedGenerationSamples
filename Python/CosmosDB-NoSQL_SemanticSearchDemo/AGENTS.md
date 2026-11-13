# Agent boundaries

- Default `azd up` bootstraps dependencies and runs the full pinned MovieLens
  real-embedding seed only in `postup`. `postprovision` is config-only.
  Restore all 4,489 source rows, including duplicate movie IDs, with deterministic
  one-based row IDs in `movielens-4489-v1-`. Retain source movie ID and metadata.
  Enforce pinned raw bytes/hash/count. Discard source 256-dimensional vectors;
  generate and cache real 1536-dimensional embeddings under ignored `.local/`.
  After ALL targets pass complete readback, the explicit hook cleanup flag may
  delete ONLY the ten exact unchanged `original-movies-v1-` fixtures, matching
  full source data, ownership and provenance, using conditional etags. Never
  delete by prefix or alter unrelated/changed records. This narrowly supersedes
  the old ten-row/no-deletes default. The tiny fixture is only smoke/offline data.
  `pwsh ./scripts/start.ps1` loads generated config and supervises the local app;
  startup has no writes. See README.md for this default, README.manual.md for
  the older synthetic integration workflow.

- `preup` persists/reuses `AZURE_COSMOS_ACCOUNT_NAME` and resets
  `AZURE_CREATE_INFERENCE=false`, without target guessing, credentials or Azure
  requests. `preprovision` uses azd's resolved selection for the mandatory
  authenticated inference GET; only HTTP 404 authorizes creation.
  `postprovision` generates private config only. `postup` performs the real seed.
  Default infrastructure includes keyless OpenAI; no manual loader is required.

- Work only in this sample unless the requester explicitly expands scope.
- Read the root README and the applicable `cosmosdb-best-practices` skill before
  Cosmos SDK changes. No account/database provisioning, role changes or cleanup
  without explicit authorization.
- Keep the original Streamlit index selector, input, reranker checkbox, four search
  buttons, all/any radio, metadata table and timing displays.
- Use `azure.data.ai.InferenceClient` for reranking. Map lowercase `scores`,
  `index`, `score` by index. Reject invalid/duplicate indices. Never silently
  present retrieval results as successfully reranked.
- Import/startup must not connect or write. Use existing database/container clients.
  OpenAI is lazy and optional for full-text search and preembedded loading.
- Inference setup is explicit and read-only by default. Use the same Cosmos account
  name, GET before creation, and the returned endpoint. `--confirm-create` and
  `--assign-role` authorize separate actions. Never redeploy Cosmos or add keys.
- Alternatively, explicitly authorized `azd provision` creates a new backend
  in its own group. Read [all prerequisites](infra/azd/README.md) first.
  Preserve ignored `.azure/` state and the persisted letter-leading GUID.
  Never bypass the preprovision inference existence check or treat 403 as 404.
  After provisioning, dot-source `. ./.local/azd-env.ps1`; do not manually copy
  endpoints or commit generated config. Report all created accounts, including
  partial deployments; do not run `azd down` without cleanup authorization.
- Preserve the Cosmos timeout regression: `connection_timeout=30` is seconds;
  never reintroduce legacy `request_timeout=30`, which is milliseconds.
- Offline tests allow loopback runtime IPC only. Keep external TCP, UDP and DNS
  blocked and keep service seams mocked.
- Never commit `.env`, virtual environments, private endpoints, subscription/account
  identifiers, tokens, private feeds, service logs or internal attachments.
- Legacy integration fixtures use original MIT-licensed text and deterministic
  vectors; they do not measure embedding quality. Default MovieLens restoration
  uses real embeddings from the deployed model. Keep namespaces stable.
- Test first. Do not claim live verification from mocks or HTTP health.

## Offline/manual development commands from the sample root

```powershell
python -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-dev.txt
& .\.venv\Scripts\python.exe scripts/make-fixtures.py
& .\.venv\Scripts\python.exe -m pytest -q tests/unit tests/ui
& .\.venv\Scripts\python.exe -m streamlit run src/app/cosmos-app.py
```

README.md covers automatic provisioning and real-embedding seeding; README.manual.md
covers the separate legacy fixture workflow. Live tests require private environment
settings, `RUN_LIVE_TESTS=1`, and the dataset belonging to the selected suite.
Write tests additionally require `ALLOW_FIXTURE_UPSERT=1`. Enabled tests must fail,
not skip, when prerequisites are missing. Never execute cleanup as part of testing.
Do not commit or push unless explicitly asked. Return changed files, commands,
actual outputs, unverified gates and remaining limitations.
