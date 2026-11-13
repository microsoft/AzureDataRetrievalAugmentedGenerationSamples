targetScope = 'resourceGroup'

param accountName string
param principalId string
param location string = 'uksouth'
@allowed(['text-embedding-3-small', 'text-embedding-3-large'])
param modelName string = 'text-embedding-3-small'
param modelVersion string = '1'
param deploymentName string = 'text-embedding-3-small'
@allowed(['GlobalStandard', 'Standard', 'DataZoneStandard'])
param skuName string = 'GlobalStandard'
@minValue(1)
@maxValue(100)
param capacity int = 30

resource account 'Microsoft.CognitiveServices/accounts@2024-10-01' = {
  name: 'aoai-${accountName}'
  location: location
  kind: 'OpenAI'
  sku: {
    name: 'S0'
  }
  properties: {
    customSubDomainName: 'aoai-${accountName}'
    disableLocalAuth: true
    publicNetworkAccess: 'Enabled'
  }
}

resource deployment 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = {
  parent: account
  name: deploymentName
  sku: {
    name: skuName
    capacity: capacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: modelName
      version: modelVersion
    }
    versionUpgradeOption: 'NoAutoUpgrade'
  }
}

var openAiUserRole = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
resource assignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: account
  name: guid(account.id, principalId, openAiUserRole)
  properties: {
    principalId: principalId
    principalType: 'User'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', openAiUserRole)
  }
}

output endpoint string = account.properties.endpoint
output deployedName string = deployment.name
