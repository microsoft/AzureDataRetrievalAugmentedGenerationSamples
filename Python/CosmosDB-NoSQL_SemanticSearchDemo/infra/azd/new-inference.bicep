targetScope = 'resourceGroup'

param accountName string
param location string

resource inference 'Microsoft.InferenceService/inferenceAccounts@2026-10-15' = {
  name: accountName
  location: location
}

output endpoint string = inference.properties.endpoint
