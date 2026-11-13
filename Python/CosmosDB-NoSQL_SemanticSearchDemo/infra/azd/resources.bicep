targetScope = 'resourceGroup'

@minLength(36)
@maxLength(36)
@description('Canonical lowercase UUID starting a-f, already validated and persisted by preprovision.')
param cosmosAccountName string
param location string
param principalId string
param includeDotnet bool = false
@allowed(['true', 'false'])
param createInference string

// Both resources consume the same persisted name. No Bicep-generated fallback.
var sampleDatabaseName = 'reranker'
var cosmosRoleId = '00000000-0000-0000-0000-000000000002'
var inferenceRoleId = '6c74a7c5-4a87-40f9-bb03-61e49aecbc78'
var pythonContainers = [
  {
    name: 'search_qflat'
    index: 'quantizedFlat'
  }
  {
    name: 'search_diskann'
    index: 'diskANN'
  }
]
var dotnetContainers = [
  {
    name: 'reranker_dotnet_qflat'
    index: 'quantizedFlat'
  }
  {
    name: 'reranker_dotnet_diskann'
    index: 'diskANN'
  }
]
var containerDefinitions = concat(pythonContainers, includeDotnet ? dotnetContainers : [])

resource cosmos 'Microsoft.DocumentDB/databaseAccounts@2025-05-01-preview' = {
  name: cosmosAccountName
  location: location
  kind: 'GlobalDocumentDB'
  properties: {
    databaseAccountOfferType: 'Standard'
    disableLocalAuth: true
    publicNetworkAccess: 'Enabled'
    consistencyPolicy: {
      defaultConsistencyLevel: 'Session'
    }
    locations: [
      {
        locationName: location
        failoverPriority: 0
        isZoneRedundant: false
      }
    ]
    capabilities: [
      { name: 'EnableNoSQLVectorSearch' }
      // Retain the capability accepted by the validated preview service account.
      { name: 'EnableNoSQLFullTextSearchPreviewFeatures' }
    ]
  }
}

resource database 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2025-05-01-preview' = {
  parent: cosmos
  name: sampleDatabaseName
  properties: {
    resource: {
      id: sampleDatabaseName
    }
  }
}

resource containers 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2025-05-01-preview' = [for container in containerDefinitions: {
  parent: database
  name: container.name
  properties: {
    resource: {
      id: container.name
      partitionKey: {
        paths: [ '/id' ]
        kind: 'Hash'
        version: 2
      }
      vectorEmbeddingPolicy: {
        vectorEmbeddings: [
          {
            path: '/embedding'
            dataType: 'float32'
            dimensions: 1536
            distanceFunction: 'cosine'
          }
        ]
      }
      fullTextPolicy: {
        defaultLanguage: 'en-US'
        fullTextPaths: [
          {
            path: '/text'
            language: 'en-US'
          }
        ]
      }
      indexingPolicy: {
        automatic: true
        indexingMode: 'consistent'
        includedPaths: [
          { path: '/*' }
        ]
        excludedPaths: [
          { path: '/"_etag"/?' }
          { path: '/embedding/*' }
        ]
        vectorIndexes: [
          {
            path: '/embedding'
            type: container.index
          }
        ]
        fullTextIndexes: [
          { path: '/text' }
        ]
      }
    }
    options: {
      throughput: 400
    }
  }
}]

// Reuse existing inference accounts. Preflight selects creation only on HTTP 404.
module newInference 'new-inference.bicep' = if (createInference == 'true') {
  name: 'create-inference'
  params: {
    accountName: cosmosAccountName
    location: location
  }
  dependsOn: [cosmos]
}

resource inference 'Microsoft.InferenceService/inferenceAccounts@2026-10-15' existing = {
  name: cosmosAccountName
}

resource cosmosAssignment 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2025-05-01-preview' = {
  parent: cosmos
  name: guid(cosmos.id, principalId, cosmosRoleId)
  properties: {
    principalId: principalId
    roleDefinitionId: '${cosmos.id}/sqlRoleDefinitions/${cosmosRoleId}'
    scope: cosmos.id
  }
}

resource inferenceAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  dependsOn: [newInference]
  scope: inference
  name: guid(inference.id, principalId, inferenceRoleId)
  properties: {
    principalId: principalId
    principalType: 'User'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', inferenceRoleId)
  }
}

output accountName string = cosmosAccountName
output cosmosAccountId string = cosmos.id
output cosmosEndpoint string = cosmos.properties.documentEndpoint
output databaseName string = sampleDatabaseName
output inferenceAccountId string = inference.id
output inferenceEndpoint string = createInference == 'true' ? newInference!.outputs.endpoint : inference.properties.endpoint
