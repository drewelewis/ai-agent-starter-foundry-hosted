targetScope = 'subscription'

@minLength(1)
@maxLength(60)
param environmentName string

param location string

@description('Object ID of the developer receiving model-invocation permission.')
param principalId string

param modelDeploymentName string = 'math-tutor'
param modelName string = 'gpt-5-mini'
param modelVersion string = '2025-08-07'

@allowed([
  'GlobalStandard'
  'DataZoneStandard'
  'Standard'
])
param modelSku string = 'GlobalStandard'

@minValue(1)
param modelCapacity int = 1

var tags = {
  application: 'math-tutor'
  'azd-env-name': environmentName
}

resource resourceGroup 'Microsoft.Resources/resourceGroups@2025-04-01' = {
  name: 'rg-${environmentName}'
  location: location
  tags: tags
}

module foundry '../main.bicep' = {
  name: 'foundry'
  scope: resourceGroup
  params: {
    location: location
    tags: tags
    deployContainerRegistry: true
    deployModel: true
    principalId: principalId
    modelDeploymentName: modelDeploymentName
    modelName: modelName
    modelVersion: modelVersion
    modelSku: modelSku
    modelCapacity: modelCapacity
  }
}

output AZURE_RESOURCE_GROUP string = resourceGroup.name
output AZURE_LOCATION string = location
output AZURE_AI_ACCOUNT_NAME string = foundry.outputs.AZURE_AI_ACCOUNT_NAME
output AZURE_AI_ACCOUNT_ID string = foundry.outputs.AZURE_AI_ACCOUNT_ID
output AZURE_AI_PROJECT_NAME string = foundry.outputs.AZURE_AI_PROJECT_NAME
output AZURE_AI_PROJECT_ID string = foundry.outputs.AZURE_AI_PROJECT_ID
output AZURE_AI_PROJECT_ENDPOINT string = foundry.outputs.AZURE_AI_PROJECT_ENDPOINT
output FOUNDRY_PROJECT_ENDPOINT string = foundry.outputs.AZURE_AI_PROJECT_ENDPOINT
output AZURE_AI_PROJECT_PRINCIPAL_ID string = foundry.outputs.AZURE_AI_PROJECT_PRINCIPAL_ID
output AZURE_TENANT_ID string = subscription().tenantId
output AZURE_OPENAI_ENDPOINT string = foundry.outputs.AZURE_OPENAI_ENDPOINT
output AZURE_AI_MODEL_DEPLOYMENT_NAME string = foundry.outputs.AZURE_AI_MODEL_DEPLOYMENT_NAME
output AZURE_CONTAINER_REGISTRY_NAME string = foundry.outputs.AZURE_CONTAINER_REGISTRY_NAME
output AZURE_CONTAINER_REGISTRY_ENDPOINT string = foundry.outputs.AZURE_CONTAINER_REGISTRY_ENDPOINT
output AZURE_CONTAINER_REGISTRY_RESOURCE_ID string = foundry.outputs.AZURE_CONTAINER_REGISTRY_ID
output AZURE_AI_PROJECT_ACR_CONNECTION_NAME string = foundry.outputs.AZURE_AI_PROJECT_ACR_CONNECTION_NAME
