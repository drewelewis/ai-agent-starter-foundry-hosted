targetScope = 'resourceGroup'

@description('Azure region supporting Foundry hosted agents. Confirm availability before deployment.')
param location string = resourceGroup().location

@minLength(2)
@maxLength(64)
@description('Globally unique Foundry account name and custom subdomain. Use lowercase letters, numbers, and hyphens.')
param foundryAccountName string = 'foundry-${uniqueString(resourceGroup().id)}'

@minLength(2)
@maxLength(64)
@description('Project name within the Foundry account.')
param foundryProjectName string = 'math-tutor'

@minLength(5)
@maxLength(50)
@description('Globally unique registry name. Use lowercase letters and numbers only.')
param containerRegistryName string = 'acr${uniqueString(resourceGroup().id)}'

@description('Tags applied to the Foundry account, project, and registry.')
param tags object = {
  application: 'math-tutor'
}

@description('Deploy a model in the new account. Leave false when using an existing model resource.')
param deployModel bool = false

param modelDeploymentName string = 'math-tutor'
param modelName string = ''
param modelVersion string = ''

@allowed([
  'GlobalStandard'
  'DataZoneStandard'
  'Standard'
])
param modelSku string = 'GlobalStandard'

@minValue(1)
param modelCapacity int = 1

@description('Create the registry and project image-pull connection needed for hosted agents.')
param deployContainerRegistry bool = true

@description('Optional developer object ID receiving model-invocation permission on this account.')
param principalId string = ''

resource foundryAccount 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: foundryAccountName
  location: location
  tags: tags
  kind: 'AIServices'
  sku: {
    name: 'S0'
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    allowProjectManagement: true
    customSubDomainName: foundryAccountName
    disableLocalAuth: true
    publicNetworkAccess: 'Enabled'
  }
}

resource foundryProject 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' = {
  parent: foundryAccount
  name: foundryProjectName
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    displayName: 'Math Tutor'
    description: 'Microsoft Foundry project for the math tutor hosted agent.'
  }
}

resource containerRegistry 'Microsoft.ContainerRegistry/registries@2025-11-01' = if (deployContainerRegistry) {
  name: containerRegistryName
  location: location
  tags: tags
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: false
    anonymousPullEnabled: false
    publicNetworkAccess: 'Enabled'
    roleAssignmentMode: 'LegacyRegistryPermissions'
  }
}

var acrPullRoleId = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7f951dda-4ed3-4680-a7ca-43fe172d538d')

resource projectAcrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (deployContainerRegistry) {
  name: guid(containerRegistry.id, foundryProject.id, acrPullRoleId)
  scope: containerRegistry
  properties: {
    principalId: foundryProject.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: acrPullRoleId
  }
}

resource registryConnection 'Microsoft.CognitiveServices/accounts/projects/connections@2025-06-01' = if (deployContainerRegistry) {
  parent: foundryProject
  name: 'container-registry'
  properties: {
    category: 'ContainerRegistry'
    authType: 'ManagedIdentity'
    target: containerRegistry!.properties.loginServer
    isSharedToAll: true
    credentials: {
      clientId: foundryProject.identity.principalId
      resourceId: containerRegistry.id
    }
    metadata: {
      ResourceId: containerRegistry.id
    }
  }
}

var modelUserRoleId = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd')

resource developerModelUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(principalId)) {
  name: guid(foundryAccount.id, principalId, modelUserRoleId)
  scope: foundryAccount
  properties: {
    principalId: principalId
    principalType: 'User'
    roleDefinitionId: modelUserRoleId
  }
}

resource modelDeployment 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = if (deployModel) {
  parent: foundryAccount
  name: modelDeploymentName
  // Foundry rejects concurrent project/model writes on the parent account.
  dependsOn: [
    foundryProject
  ]
  sku: {
    name: modelSku
    capacity: modelCapacity
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

output AZURE_RESOURCE_GROUP string = resourceGroup().name
output AZURE_LOCATION string = location
output AZURE_AI_ACCOUNT_NAME string = foundryAccount.name
output AZURE_AI_ACCOUNT_ID string = foundryAccount.id
output AZURE_AI_PROJECT_NAME string = foundryProject.name
output AZURE_AI_PROJECT_ID string = foundryProject.id
output AZURE_AI_PROJECT_ENDPOINT string = foundryProject.properties.endpoints['AI Foundry API']
output AZURE_AI_PROJECT_PRINCIPAL_ID string = foundryProject.identity.principalId
output AZURE_OPENAI_ENDPOINT string = foundryAccount.properties.endpoints['OpenAI Language Model Instance API']
output AZURE_CONTAINER_REGISTRY_NAME string = deployContainerRegistry ? containerRegistry!.name : ''
output AZURE_CONTAINER_REGISTRY_ID string = deployContainerRegistry ? containerRegistry!.id : ''
output AZURE_CONTAINER_REGISTRY_ENDPOINT string = deployContainerRegistry ? containerRegistry!.properties.loginServer : ''
output AZURE_AI_MODEL_DEPLOYMENT_NAME string = deployModel ? modelDeploymentName : ''
output AZURE_AI_PROJECT_ACR_CONNECTION_NAME string = deployContainerRegistry ? registryConnection!.name : ''
