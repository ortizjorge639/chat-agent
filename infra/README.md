# Infrastructure Setup for Azure Resources

This repository contains the infrastructure as code (IaC) setup for deploying various Azure resources using Bicep. The following resources are defined:

1. **Azure App Service**: A module for hosting Python applications on a Linux environment.
2. **Azure Bot Service**: A module for creating and managing a bot service.
3. **Azure OpenAI**: A module for integrating OpenAI services into your applications.

## Directory Structure

- **main.bicep**: The main entry point for the Bicep deployment, orchestrating the deployment of all modules.
- **parameters.json**: Contains parameters for the main Bicep file, allowing customization of the deployment.
- **modules/**: Contains individual modules for each Azure resource.
  - **appservice/**: Contains the Bicep file and parameters for the Azure App Service.
  - **botservice/**: Contains the Bicep file and parameters for the Azure Bot Service.
  - **openai/**: Contains the Bicep file and parameters for the Azure OpenAI service.
- **pipelines/**: Contains the Azure DevOps pipeline configuration file.

## Deployment Instructions

1. Ensure you have the Azure CLI and Bicep CLI installed.
2. Customize the `parameters.json` files as needed for your deployment.
3. Deploy the infrastructure using the following command:

   ```bash
   az deployment group create --resource-group <your-resource-group> --template-file main.bicep --parameters parameters.json
   ```

4. Follow the instructions in the `azure-pipelines.yml` file to set up your Azure DevOps pipeline for continuous integration and deployment.

## Prerequisites

- An Azure subscription.
- Azure CLI installed and configured.
- Bicep CLI installed.

For further details on each module, please refer to the respective README files within the module directories.