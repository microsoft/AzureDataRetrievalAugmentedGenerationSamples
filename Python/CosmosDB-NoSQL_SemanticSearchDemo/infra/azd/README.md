# azd: new backend resources, local applications

This path is separate from the existing-resource setup in `../README.md`.
Run azd from the directory containing the selected `azure.yaml`, not this
infra directory. No web app, App Service plan, container image or cloud
application deployment is included. Use `azd up` for dependency bootstrap,
backends, private config and full pinned MovieLens restoration with real embeddings.
`azd provision` deliberately performs no seeding. Azure OpenAI is now included.

| Hook | Responsibility |
| --- | --- |
| `preup` | Bootstrap dependencies and persist/reuse `AZURE_COSMOS_ACCOUNT_NAME`; reset `AZURE_CREATE_INFERENCE=false` without credentials or Azure requests. |
| `preprovision` | Mandatory authenticated inference GET using azd's resolved subscription/location; only HTTP 404 authorizes creation. |
| `postprovision` | Generate private local configuration, including the deployed embedding settings. |
| `postup` | Restore all 4,489 pinned MovieLens source rows with cached real 1536-dimensional embeddings; verify every target before conditionally removing only the exact ten unchanged legacy fixtures. Never alter unrelated records. |

## All prerequisites

These apply even if already installed or authorized on your workstation.
The implementation host reported azd 1.25.6, PowerShell 7.4.20 and Bicep
0.47.16 installed. That is a tool inventory, not fresh-deployment evidence.
An upgrade to the latest azd is not required merely to use this sample.

| Prerequisite | Required action/check |
| --- | --- |
| Git | Install, clone the intended branch, run from this sample or the combined repository root. `git --version`. |
| Azure Developer CLI | Install azd; implementation baseline 1.25.6. `azd version`. Authenticate with `azd auth login`. |
| Azure CLI | Install and run `az version`, `az login --tenant <tenant-id>`, `az account set --subscription <subscription-id>`. Required by inference preflight via `AzureCliCredential`, local `DefaultAzureCredential`, and verification/existing-resource commands. The postprovision configuration writer uses azd instead. |
| PowerShell 7 | `pwsh --version`. Required for hooks on Windows, Linux and macOS. Windows PowerShell 5.1 is not sufficient. Launch `pwsh` for all quickstart commands. |
| Python 3.10+, venv, pip | Install Python/venv/pip. Preprovision creates the venv and installs both requirements files. On Linux install the distribution's venv package if necessary. On macOS/Linux bootstrap uses `python3`. |
| .NET 10 SDK | Required only for the combined root's .NET app/tests. `dotnet --list-sdks`. Not required for standalone Python. |
| Bicep | azd manages its Bicep compiler. `az bicep version` / `az bicep install` manage Azure CLI's separate compiler for explicit compile checks. A standalone `bicep` executable is optional, not another mandatory install. New preview resource types may produce type-information warnings; ARM acceptance is a separate gate. |
| Public network and trusted TLS | Access to Azure login, ARM, Cosmos, inference, PyPI, NuGet, azd/Bicep downloads and package feeds. Install required corporate CA trust correctly; never disable certificate validation. Cosmos .NET Direct mode also needs its documented outbound TCP connectivity; `COSMOS_CONNECTION_MODE=Gateway` is an alternative on HTTPS-only networks. |
| Identity, subscription, tenant | Use the same Entra user in azd and Azure CLI. Set the intended subscription in both. `azd auth login` does not replace `az login` for local SDK credentials. Remove stale service-principal credential variables or choose a clean shell if they cause DefaultAzureCredential to use another identity. |
| Subscription permissions | Permission to create a resource group and the resources at subscription scope, create Cosmos SQL role assignments, and create Azure RBAC role assignments. Contributor alone cannot grant all RBAC roles. Owner or an equivalent combination of resource Contributor and RBAC administration is needed. |
| Registered providers | `Microsoft.DocumentDB`, `Microsoft.InferenceService`, and `Microsoft.CognitiveServices` must be registered. Registration needs permission and may take time; it does not guarantee service availability. |
| Availability, policy and quota | Confirm inference API/region access, Cosmos account and provisioned RU quotas, and subscription policies. Default is `uksouth`; this template allows `uksouth`, `eastus2`, `westus3`. Both accounts use the selected region. |
| Data roles and propagation | IaC grants the signed-in azd user Cosmos Built-in Data Contributor on the new account and Semantic Reranker User on the new inference account. Wait for propagation before loading/searching. Do not respond to 403 by enabling keys or broadening roles. |
| Paid resources | Dedicated manual 400 RU/s per container, continuously billed until removal, plus storage and inference charges. Python creates two containers (800 RU/s); combined root creates four (1600 RU/s). No 10,000 RU/s default or autoscale. Review current Azure pricing before provisioning. |
| Real embeddings | Included keyless OpenAI account with custom subdomain and scoped Cognitive Services OpenAI User role. Default UKSouth `text-embedding-3-small` version 1, GlobalStandard capacity 30 requires available quota. Global processing is not limited to UKSouth. Pay-per-token, not provisioned throughput. Configure model/version/deployment/SKU/capacity/region with variables documented in the sample README. Unavailable model or quota fails; no fake vectors or automatic fallback. |
| Optional browser tooling | Browser for manual interaction. Playwright/browser downloads only for the separate real browser tests. Docker is **not required**. |
| Private azd state | Keep the selected environment's ignored `.azure/` state. The preprovision hook persists `AZURE_COSMOS_ACCOUNT_NAME` before ARM runs. Losing this state after partial provisioning can create another account; inspect Azure before recovering state. Do not copy an environment's name into another environment. |

Check registration without changing it:

```powershell
az provider show --namespace Microsoft.DocumentDB --query registrationState -o tsv
az provider show --namespace Microsoft.InferenceService --query registrationState -o tsv
az role definition list --name 'Semantic Reranker User' --query '[].{name:roleName,id:name}' -o table
azd config show
```

Only an authorized operator should run these if registration is missing:

```powershell
az provider register --namespace Microsoft.DocumentDB --wait
az provider register --namespace Microsoft.InferenceService --wait
```

No `auth.useAzCliAuth` override is required. Do not persist private package
sources in this repository. Use normal public sources with trusted TLS.

The preprovision hook also uses `AzureCliCredential` to perform an authenticated
ARM GET for the exact inference account. HTTP 404 permits creation; an existing
compatible, ready, keyless account is referenced without a repeated PUT.
Only absence authorizes creation. Other status codes fail explicitly.
`AZURE_CREATE_INFERENCE` is recalculated and persisted on every run, never inferred
from old outputs. Azure CLI login and ARM read permission are therefore required
before provisioning as well as before running the apps. Do not bypass the hook.

## Resource contract and evidence

- Dedicated group: `rg-reranker-<AZURE_ENV_NAME>`, tagged `azd-env-name`.
  Choose an unused environment name unique across all these projects in the
  subscription. Do not point this path at a preexisting group. Names use
  1-40 lowercase letters/digits/hyphens, starting with a letter or digit.
- Both accounts use the persisted `AZURE_COSMOS_ACCOUNT_NAME`: a canonical
  lowercase 36-character UUID whose first character is **a-f**. Inference
  rejects digit-leading names even when Cosmos accepts them. Before any ARM
  deployment, `scripts/prepare_azd.py` reuses the existing persisted valid name
  or adopts a validated existing `COSMOS_ACCOUNT_NAME` output. Otherwise it
  samples complete `uuid.uuid4()` values until one starts a-f, with an explicit
  error after 128 unsuccessful attempts. It never edits UUID bytes, adds a
  prefix, or relies on Bicep retry candidates. The name is persisted with
  `azd env set` and verified before provisioning. Unrelated metadata is preserved.
  Bicep consumes that required parameter with length constraints and no default
  or generated fallback; the hook enforces the full shape. Freeform names fail.
  Reprovision reuses the stored UUID. Different fresh environments independently
  generate names; the name is **not derived from** the environment/group and
  is not a credential. Never delete valid naming state to force a new name.
- Cosmos API `2025-05-01-preview`, NoSQL, Entra-only (`disableLocalAuth`),
  one region, Session consistency, public endpoint for local development.
  Stable Inference API `2026-10-15`, same name and location, location-only
  request body and service-returned `properties.endpoint`. Keys are disabled
  by the inference service default; the template does not enable/request them.
- Database `reranker`. Python: `search_qflat`, `search_diskann`.
  Combined root additionally: `reranker_dotnet_qflat`, `reranker_dotnet_diskann`.
  Each has `/id` Hash partitioning, `/embedding` float32/1536/cosine,
  quantizedFlat or diskANN, `/text` en-US policy/full-text index, consistent
  indexing, and scalar `/embedding/*` exclusion. No shared database offer.
- Capabilities: `EnableNoSQLVectorSearch` and
  `EnableNoSQLFullTextSearchPreviewFeatures`. The latter retains the
  preview flag accepted on fresh Cosmos deployments during validation. Current
  [public sample Bicep](https://github.com/AzureCosmosDB/cosmosdb-nosql-copilot/blob/main/infra/core/database/cosmos-db/account.bicep)
  uses the shorter `EnableNoSQLFullTextSearch`. That does not establish that
  the shorter flag works for this preview API/subscription. The exact preview
  spelling could not be independently located in public documentation.
  Fresh account provisioning accepted this spelling, and the standalone Python
  live suite passed on the new backend. Do not silently
  replace it on failure; check service support and report diagnostics.
- Cosmos role `00000000-0000-0000-0000-000000000002`, scope new Cosmos account.
  Inference role `6c74a7c5-4a87-40f9-bb03-61e49aecbc78`, scope new inference.
  `${AZURE_PRINCIPAL_ID}` in `main.parameters.json` uses azd's signed-in
  principal convention. This quickstart targets an interactive Entra **User**,
  not a service principal or hosted managed identity.
- Outputs include both account names/IDs, group, database and endpoints.
  Inference endpoint is read from ARM, not derived from the account name.

References: [azd environment variables](https://learn.microsoft.com/azure/developer/azure-developer-cli/manage-environment-variables),
[azd hooks](https://learn.microsoft.com/azure/developer/azure-developer-cli/azd-extensibility),
[Cosmos ARM schema](https://learn.microsoft.com/azure/templates/microsoft.documentdb/2025-05-01-preview/databaseaccounts),
[Python UUID generation](https://docs.python.org/3/library/uuid.html#uuid.uuid4).

## Naming preflight and failed provisioning

The custom `up` workflow contains only `azd: provision`. `preup` performs local
bootstrap: dependencies, persisted naming, and an explicit no-create reset.
It does not resolve subscription/location, authenticate, or call Azure.
`preprovision` resets stale authorization again, then performs the mandatory
authenticated inference GET against azd's resolved selection. Missing selection
fails closed; no CLI-default fallback exists. HTTP 404 alone changes the creation
decision to `true`; an existing compatible account keeps it `false`.
Run the full preparation script
explicitly to inspect naming state without provisioning resources:

```powershell
pwsh ./scripts/preprovision.ps1
if ($LASTEXITCODE -ne 0) { throw 'Naming preflight failed' }
azd env get-value AZURE_COSMOS_ACCOUNT_NAME
```

Valid persisted names and valid existing deployed-output names are reused,
including successful deployments created before this hook existed.
Conflicting valid names fail for manual inspection, rather than renaming a
successful account. Invalid persisted names fail by default. If an earlier
deployment failed on a digit-leading UUID, first inspect its resources and
confirm that a replacement is intended. Then explicitly authorize recovery:

```powershell
# Only after inspecting a failed deployment and approving a replacement name:
pwsh ./scripts/preprovision.ps1 -RegenerateInvalidName
if ($LASTEXITCODE -ne 0) { throw 'Naming recovery failed' }
azd provision
```

This flag replaces only invalid naming state. It does not rotate a valid
name or override a valid successful deployment. When failed deployment
outputs are absent and no name was persisted, ordinary preflight generates
a new name. Inspect Azure first: missing outputs do not prove no resources
exist. Do not manually edit a UUID or set a freeform resource name.

**Provisioning is not transactional.** A failed inference deployment can
leave a paid Cosmos account, database and containers. A replacement account
can coexist with those partial resources in the dedicated group. These hooks
do not delete or roll back Azure resources. Record partial and replacement
accounts separately; keep them for inspection until cleanup is authorized.

### Hook parameter-refresh verification

When validating lifecycle changes, start with no `.azure` state and run only
`azd up` with an explicit environment, subscription and location. Do not count
an earlier `azd env new`, `init`, or failed first attempt as a first-use pass.
Inspect the actual ARM deployment parameter, not only azd environment readback:

```powershell
# Supply the same explicit subscription and environment used for azd up.
az deployment group show --subscription $subscription `
  --resource-group "rg-reranker-$environment" --name reranker-backend `
  --query 'properties.parameters.createInference.value' -o tsv
```

A successful fresh deployment must record `true`; a successful repeat must record
`false`, with the same account GUID. If the fresh deployment receives the bootstrap
`false` instead of the authenticated decision, stop: parameter refresh is not
verified. Do not bypass the GET, force creation, or retry inference PUT manually.

## Generated local configuration

The postprovision hook reads `azd env get-values --output json` in the
selected project. It validates required outputs before writing anything.
Malformed output, missing values, invalid UUID, inconsistent IDs, unsafe
URLs, or malformed existing dotenv bindings fail the hook. There is no
shell evaluation of azd text. Output values are never copied into tracked files.

| Destination | Generated values |
| --- | --- |
| Python `.env` | `COSMOS_URI`, `COSMOS_DB_DATABASE`, `AZURE_AI_INFERENCE_ENDPOINT`, OpenAI endpoint/deployment/model/version/API version, and `AZURE_OPENAI_AUTH_MODE=entra` |
| `.local/azd-env.ps1` | Same values plus account/group/environment metadata for inspection |
| Combined root `.local/azd-env.ps1` | Also `COSMOS_DB_ENDPOINT`, `INFERENCE_ENDPOINT`, `COSMOS_DB_CONTAINER_QFLAT`, `COSMOS_DB_CONTAINER_DISKANN` |
| Combined root `python/` | Its `.env` and `.local/azd-env.ps1` are refreshed too |

Only the managed Python dotenv bindings are replaced. Unrelated values,
including multiline bindings, are preserved. OpenAI deployment settings are
managed by azd; any preserved manual API key is ignored in generated Entra mode.
Files are staged before replacement, with rollback on ordinary write errors.
After an interrupted process or machine failure, stop apps and rerun the
hook before using config. Do not run configuration writers concurrently.
azd `.azure/`, `.env` and `.local/` are ignored at every project entry point.
No tokens/keys are obtained, and no user/machine-global environment is changed.

A hook is a subprocess: it **cannot update the calling shell**. Dot-source:

```powershell
. ./.local/azd-env.ps1
```

Python also reads its `.env` directly. Existing process variables take
precedence, so always dot-source again after switching and restart apps.
.NET does not load `.env`; it receives the dot-sourced process environment.
`DEMO_LOAD_DOTENV=false` disables Python dotenv loading. Dot-sourcing still
supplies its required values. Review credential settings when switching tenants.
The launcher dot-sources config automatically for its owned app processes.

## Refresh, switch, reprovision

Stop running apps first. Select the desired project/environment explicitly:

```powershell
azd env select reranker-python-dev
azd env refresh
pwsh ./scripts/postprovision.ps1
if ($LASTEXITCODE -ne 0) { throw 'Configuration refresh failed' }
. ./.local/azd-env.ps1
```

Replace the environment name with the combined root's name when there.
Do not rely on refresh invoking hooks; the explicit hook call is intentional.
For a new environment, run `azd up` directly, optionally passing
`--environment <unique-name> --subscription <id> --location uksouth`.
No prior environment-creation command is required. Valid persisted account
names are not overridden. Reprovision regenerates local config automatically; select
the environment first instead of using an unrelated shell's cached settings.

## Inspect and clean up

After dot-sourcing, inspect only this environment:

```powershell
az cosmosdb list --subscription $env:AZURE_SUBSCRIPTION_ID `
  --resource-group $env:AZURE_RESOURCE_GROUP `
  --query '[].{name:name,id:id,endpoint:documentEndpoint,localAuthDisabled:disableLocalAuth,capabilities:capabilities[].name}' -o json
az resource show --ids $env:INFERENCE_ACCOUNT_ID --api-version 2026-10-15 `
  --query '{name:name,id:id,endpoint:properties.endpoint}' -o json
az cognitiveservices account list --subscription $env:AZURE_SUBSCRIPTION_ID `
  --resource-group $env:AZURE_RESOURCE_GROUP `
  --query '[].{name:name,id:id,location:location,localAuthDisabled:properties.disableLocalAuth}' -o json
```

Keep account inventory and live logs private. Do not execute cleanup in
tests: leave resources and documents available for inspection.

**Destructive, optional cleanup only:** select the correct environment,
inspect its group/output IDs, then run `azd down`. Review its prompt: it
deletes that environment's dedicated group and all its data/resources.
Never add unrelated resources to that group. This does not clean other
azd projects or the older existing-resource setup. Delete generated local
config and close shells/apps afterwards so deleted endpoints are not reused.
