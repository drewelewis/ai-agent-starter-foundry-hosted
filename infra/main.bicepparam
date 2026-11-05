using './main.bicep'

// Example only: verify hosted-agent availability in this region before deployment.
param location = 'northcentralus'

param foundryProjectName = 'math-tutor'

param tags = {
  application: 'math-tutor'
  environment: 'dev'
}
