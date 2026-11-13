targetScope = 'subscription'

@minLength(1)
@maxLength(40)
@description('Unique azd environment name. Use lowercase letters, digits and hyphens.')
param environmentName string

@allowed([
  'uksouth'
  'eastus2'
  'westus3'
])
param location string = 'uksouth'

@minLength(36)
@maxLength(36)
@description('Signed-in azd user object ID, supplied by AZURE_PRINCIPAL_ID.')
param principalId string

@minLength(36)
@maxLength(36)
@description('Persisted lowercase UUID starting a-f. Validated by the preprovision hook; never invent or change an existing name.')
param cosmosAccountName string
@allowed(['true', 'false'])
param createInference string

param openAiLocation string = 'uksouth'
@allowed(['text-embedding-3-small', 'text-embedding-3-large'])
param embeddingModel string = 'text-embedding-3-small'
param embeddingVersion string = '1'
param embeddingDeployment string = 'text-embedding-3-small'
@allowed(['GlobalStandard', 'Standard', 'DataZoneStandard'])
param embeddingSku string = 'GlobalStandard'
@minValue(1)
@maxValue(100)
param embeddingCapacity int = 30

resource group 'Microsoft.Resources/resourceGroups@2021-04-01' = {
  name: 'rg-reranker-${environmentName}'
  location: location
  tags: {
    'azd-env-name': environmentName
    'sample': 'standalone-semantic-reranker'
  }
}

module backend 'resources.bicep' = {
  name: 'reranker-backend'
  scope: group
  params: {
    cosmosAccountName: cosmosAccountName
    createInference: createInference
    location: location
    principalId: principalId
    includeDotnet: false
  }
}

output AZURE_RESOURCE_GROUP string = group.name
output COSMOS_ACCOUNT_NAME string = backend.outputs.accountName
output COSMOS_ACCOUNT_ID string = backend.outputs.cosmosAccountId
output COSMOS_URI string = backend.outputs.cosmosEndpoint
output COSMOS_DB_DATABASE string = backend.outputs.databaseName
output INFERENCE_ACCOUNT_NAME string = backend.outputs.accountName
output INFERENCE_ACCOUNT_ID string = backend.outputs.inferenceAccountId
output AZURE_AI_INFERENCE_ENDPOINT string = backend.outputs.inferenceEndpoint

module embeddings 'embeddings.bicep' = {
  name: 'embeddings'
  scope: group
  params: {
    accountName: cosmosAccountName
    principalId: principalId
    location: openAiLocation
    modelName: embeddingModel
    modelVersion: embeddingVersion
    deploymentName: embeddingDeployment
    skuName: embeddingSku
    capacity: embeddingCapacity
  }
}

output AZURE_OPENAI_ENDPOINT string = embeddings.outputs.endpoint
output AZURE_OPENAI_EMBEDDING_DEPLOYMENT string = embeddings.outputs.deployedName
output AZURE_OPENAI_EMBEDDING_MODEL string = embeddingModel
output AZURE_OPENAI_EMBEDDING_VERSION string = embeddingVersion
output AZURE_OPENAI_API_VERSION string = '2024-02-01'
