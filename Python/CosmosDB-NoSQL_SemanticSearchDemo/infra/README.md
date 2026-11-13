# Explicit provisioning boundaries

The app and loader do not provision resources. Provisioning is an operator step.
Use an existing Cosmos DB account and SQL database. Do not redeploy or alter them
to enable this sample. Do not grant the web app control-plane permissions.

## Containers

From the sample root:

```powershell
& .\.venv\Scripts\python.exe src/container_setup.py `
  --subscription $subscription --resource-group $resourceGroup `
  --account $account --database $database --confirm-create
```

The script creates only missing `search_qflat` and `search_diskann` at 400 RU/s
each, with the policies in `src/container_setup.py`. It validates both existing
policies before creating either container. Compatible containers are reused
without throughput changes. Account and database creation, capability changes,
role assignments, deletion and automatic replacement are intentionally excluded.

Container setup requires a recent Azure CLI supporting vector/full-text policy
flags and appropriate Cosmos control-plane permissions.

## Companion inference

`src/inference_setup.py` is the self-contained, explicit setup entry point.
It requires the sample dependencies and an authenticated Azure CLI session.
The companion inference account uses the **same account name, subscription and
resource group** as the existing Cosmos account. Reranking does not use the
Cosmos container SDK.

First inspect/reuse without changes:

```powershell
$location = "<supported-inference-region>"
& .\.venv\Scripts\python.exe src/inference_setup.py `
  --subscription $subscription --resource-group $resourceGroup `
  --account $account --location $location
```

The default is read-only. It GETs the existing Cosmos account and exact inference
resource. A compatible resource returns `action: reused` and its actual
`properties.endpoint`. An absent resource returns `action: would-create`, with
no endpoint or role assignment. Permission/network errors are not treated as
absence. Incompatible existing resources are rejected, never overwritten.

For a new companion only, an authorized operator must first ensure the provider
is registered. Inspect it first:

```powershell
az provider show --subscription $subscription --namespace Microsoft.InferenceService `
  --query registrationState -o tsv
```

If not registered, an authorized administrator can explicitly run:

```powershell
az provider register --subscription $subscription --namespace Microsoft.InferenceService --wait
```

Then explicitly authorize creation:

```powershell
& .\.venv\Scripts\python.exe src/inference_setup.py `
  --subscription $subscription --resource-group $resourceGroup `
  --account $account --location $location --confirm-create
```

The script uses this control-plane contract:

```text
PUT /subscriptions/{subscription}/resourceGroups/{group}/providers/
    Microsoft.InferenceService/inferenceAccounts/{existingCosmosAccountName}
    ?api-version=2026-10-15

{"location": "<supported-region>"}
```

It rechecks the exact resource immediately before PUT, uses `If-None-Match: *`,
then polls GET for a bounded period. Do not run concurrent provisioners against
the same name. It validates the returned resource identity, location,
`provisioningState: Succeeded`, `enableKeyBasedAuthentication: false`, and HTTPS
endpoint. It **reads the endpoint from the response**, never derives it.

This script makes no Cosmos PUT, account/database deployment, capability change,
key operation or deletion. The existing Cosmos reference is verified by GET and
the companion's same-name/resource-group convention. No Cosmos reference property
is invented or added to the inference request body.

### Optional, explicitly authorized role assignment

The running identity needs **Semantic Reranker User**, independently of its Cosmos
data-plane role. To assign/reuse this role for the signed-in user:

```powershell
& .\.venv\Scripts\python.exe src/inference_setup.py `
  --subscription $subscription --resource-group $resourceGroup `
  --account $account --location $location --assign-role
```

For an existing managed identity, add
`--principal-id "<managed-identity-object-id>" --principal-type ServicePrincipal`.
Without `--principal-id`, the script resolves `az ad signed-in-user show`.
Use `--confirm-create --assign-role` together only when both actions are authorized.

The role ID is `6c74a7c5-4a87-40f9-bb03-61e49aecbc78`. The script checks for an
existing assignment at the **exact inference resource scope**, reuses it if
present, and creates only that assignment if missing. It never grants Cosmos
permissions. Skip `--assign-role` when no role-management change is authorized.
Allow propagation before invoking inference.

The returned endpoint is private configuration. Set it in
`AZURE_AI_INFERENCE_ENDPOINT`; do not commit output or resource identifiers.
The standalone SDK data-plane API version is separate from this control-plane
API version. Preview region/account availability may vary.

## App Service

See [app-service.md](app-service.md) for explicit Linux Python deployment,
managed identity, separate roles, private app settings, safe packaging and real
page-interaction verification.
