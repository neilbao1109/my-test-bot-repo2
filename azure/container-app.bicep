// ClawFS on Azure: Container App + Blob Storage (v2 backend)
@description('Base name for all resources')
param name string = 'clawfs'

@description('Azure region')
param location string = resourceGroup().location

@description('Container image (e.g. myacr.azurecr.io/clawfs:latest)')
param image string

@description('ACR resource ID for image pull (optional). When set, MI will be granted AcrPull and registry config wired up.')
param acrId string = ''

@description('ACR login server, e.g. myacr.azurecr.io. Required when acrId is set.')
param acrServer string = ''

var storageName = toLower('${name}sa${uniqueString(resourceGroup().id)}')
var envName = '${name}-env'
var appName = '${name}-app'
var containerName = 'blobs'

resource storage 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: storageName
  location: location
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: { allowBlobPublicAccess: false }
}

resource blobSvc 'Microsoft.Storage/storageAccounts/blobServices@2023-01-01' = {
  parent: storage
  name: 'default'
}

resource container 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-01-01' = {
  parent: blobSvc
  name: containerName
  properties: { publicAccess: 'None' }
}

resource logs 'Microsoft.OperationalInsights/workspaces@2022-10-01' = {
  name: '${name}-logs'
  location: location
  properties: { sku: { name: 'PerGB2018' }, retentionInDays: 30 }
}

resource env 'Microsoft.App/managedEnvironments@2023-05-01' = {
  name: envName
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logs.properties.customerId
        sharedKey: logs.listKeys().primarySharedKey
      }
    }
  }
}

resource app 'Microsoft.App/containerApps@2023-05-01' = {
  name: appName
  location: location
  identity: { type: 'SystemAssigned' }
  properties: {
    managedEnvironmentId: env.id
    configuration: {
      ingress: { external: true, targetPort: 8000, transport: 'auto' }
      registries: empty(acrServer) ? [] : [
        {
          server: acrServer
          identity: 'system'
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'clawfs'
          image: image
          resources: { cpu: json('0.5'), memory: '1Gi' }
          env: [
            { name: 'CLAWFS_BACKEND', value: 'azure' }
            { name: 'CLAWFS_AZURE_ACCOUNT_URL', value: 'https://${storage.name}.blob.${environment().suffixes.storage}' }
            { name: 'CLAWFS_AZURE_CONTAINER', value: containerName }
          ]
        }
      ]
      scale: { minReplicas: 1, maxReplicas: 3 }
    }
  }
}

// Grant AcrPull to MI when ACR is provided
var acrPullRoleId = '7f951dda-4ed3-4680-a7ca-43fe172d538d'
resource existingAcr 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = if (!empty(acrId)) {
  name: last(split(acrId, '/'))
}
resource acrPullAssign 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(acrId)) {
  name: guid(acrId, app.id, acrPullRoleId)
  scope: existingAcr
  properties: {
    principalId: app.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRoleId)
  }
}

// Grant the Container App's managed identity Blob Data Contributor on the storage account
var blobDataContributorRoleId = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
resource roleAssign 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storage.id, app.id, blobDataContributorRoleId)
  scope: storage
  properties: {
    principalId: app.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', blobDataContributorRoleId)
  }
}

output appFqdn string = app.properties.configuration.ingress.fqdn
output storageAccount string = storage.name
