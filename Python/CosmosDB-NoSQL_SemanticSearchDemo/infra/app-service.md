# Azure App Service deployment

Deploy only after local loading and search tests pass. These are explicit,
cost-incurring deployment commands for a human/operator to run, not app startup
actions. They create an App Service plan and web app only. They do not provision
Cosmos, containers, inference or OpenAI.

## 1. Create or select a Linux Python app

From the sample root, use your own private settings:

```powershell
$subscription = "<subscription-id>"
$resourceGroup = "<existing-resource-group>"
$location = "<app-service-region>"
$plan = "<new-plan-name>"
$webapp = "<globally-unique-web-app-name>"

az appservice plan create --subscription $subscription --resource-group $resourceGroup `
  --name $plan --location $location --is-linux --sku B1
az webapp create --subscription $subscription --resource-group $resourceGroup `
  --plan $plan --name $webapp --runtime "PYTHON:3.11"
```

If using an existing compatible Linux Python web app, skip creation. Confirm that
the runtime is available with `az webapp list-runtimes --os linux` if needed.
Use a dedicated app to avoid replacing another application's deployment.

## 2. Configure managed identity and separate permissions

```powershell
$principalId = az webapp identity assign --subscription $subscription `
  --resource-group $resourceGroup --name $webapp --query principalId -o tsv
```

Have an authorized administrator assign this object ID:

- A Cosmos DB data-plane read/query role scoped to the existing sample database.
  Built-in Data Reader role suffix:
  `00000000-0000-0000-0000-000000000001`.
- **Semantic Reranker User**, scoped to the companion inference resource.
- Optional **Cognitive Services OpenAI User**, scoped to the existing embedding
  resource, only when vector/hybrid UI search is needed.

The web app does not need Cosmos write or container-management permission.
Use a separate loader identity with Cosmos Data Contributor.
For example, with the existing Cosmos resource variables from the root README:

```powershell
$cosmosId = az cosmosdb show --subscription $subscription `
  --resource-group $resourceGroup --name $account --query id -o tsv
az cosmosdb sql role assignment create --subscription $subscription `
  --resource-group $resourceGroup --account-name $account `
  --principal-id $principalId `
  --role-definition-id "$cosmosId/sqlRoleDefinitions/00000000-0000-0000-0000-000000000001" `
  --scope "$cosmosId/dbs/$database"

az role assignment create --assignee-object-id $principalId `
  --assignee-principal-type ServicePrincipal --role "Semantic Reranker User" `
  --scope $inferenceId
```

Skip assignments that already exist. These operations require role-management
permission and are deliberately separate from provisioning and application code.
Allow propagation before testing. The system-assigned managed identity needs no
client secret. For a user-assigned identity, attach it and set `AZURE_CLIENT_ID`.

## 3. Configure private app settings and startup

Use the real endpoints in shell variables, not in tracked files:

```powershell
$cosmosEndpoint = "<your-private-cosmos-endpoint>"
$inferenceEndpoint = "<your-private-inference-endpoint>"

az webapp config appsettings set --subscription $subscription `
  --resource-group $resourceGroup --name $webapp --settings `
  "SCM_DO_BUILD_DURING_DEPLOYMENT=true" "DEMO_LOAD_DOTENV=false" `
  "COSMOS_URI=$cosmosEndpoint" "COSMOS_DB_DATABASE=$database" `
  "AZURE_AI_INFERENCE_ENDPOINT=$inferenceEndpoint" --output none

az webapp config set --subscription $subscription --resource-group $resourceGroup `
  --name $webapp --web-sockets-enabled true --always-on true `
  --startup-file "python -m streamlit run src/app/cosmos-app.py --server.address 0.0.0.0 --server.port 8000 --server.headless true" `
  --output none
az webapp update --subscription $subscription --resource-group $resourceGroup `
  --name $webapp --https-only true --output none
```

Oryx installs the sample-root `requirements.txt` at deployment time.
Do not install dependencies on every application startup.
For optional embeddings add `AZURE_OPENAI_ENDPOINT`,
`AZURE_OPENAI_EMBEDDING_DEPLOYMENT`, and `AZURE_OPENAI_API_VERSION` privately.
Prefer managed identity over API keys. If keys are unavoidable, use Key Vault
references rather than a packaged `.env`.

## 4. Package and deploy

```powershell
& .\.venv\Scripts\python.exe scripts/package-app.py
az webapp deploy --subscription $subscription --resource-group $resourceGroup `
  --name $webapp --src-path .local/app.zip --type zip
```

The packager includes only Python source under `src/` and dependency manifests.
It excludes `.env`, `.venv`, fixtures, tests, logs, local settings and repository
history. Review the archive before uploading. The remote app reads the documents
already loaded into Cosmos; it does not deploy or load data.

## 5. Verify the actual page

Open `https://<web-app-name>.azurewebsites.net`, enter **orbital rescue** and
execute full-text search/ranking with reranking off and on. Check:

- The expected fixture appears in the metadata table.
- Enabled reranking adds `rerank_score` and reports applied.
- An unauthorized inference request produces a visible failure, not false success.
- Both index choices work.
- The application identity cannot write data or manage resources.

An HTTP health response alone is not acceptance evidence. This repository's
AppTest suite proves local page/callback execution; also test the deployed
browser page, WebSocket connection and managed-identity permissions.

The sample does not include end-user sign-in. Restrict access using App Service
Authentication or private networking before exposing sensitive data. Budget for
App Service, Cosmos provisioned throughput and inference usage. Do not place raw
service diagnostics containing private endpoints or identifiers in public issues.
