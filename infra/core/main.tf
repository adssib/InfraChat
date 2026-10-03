# The permanent layer: one resource group and one Container Apps environment, applied once
# from the laptop. The environment is what fixes the app's hostname
# (infrachat-api.<default_domain>), so the static UI on GitHub Pages can hard-code it.
# On the Consumption plan an environment with no running app should cost $0 — M1 checks.

provider "azurerm" {
  features {}
  # Pinned: the az CLI on this machine can also see a Concordia production subscription.
  subscription_id = var.subscription_id
}

resource "azurerm_resource_group" "core" {
  name     = "rg-infrachat"
  location = var.location
  tags     = { project = "infrachat", layer = "core" }
}

resource "azurerm_container_app_environment" "env" {
  name                = "cae-infrachat"
  location            = azurerm_resource_group.core.location
  resource_group_name = azurerm_resource_group.core.name
  # logs_destination left unset: logs are streamed only, no Log Analytics workspace to pay for.
  # Azure adds this serverless profile on create; declared so Terraform stops trying to
  # remove it. Consumption-only: billed per second, no environment management fee.
  workload_profile {
    name                  = "Consumption"
    workload_profile_type = "Consumption"
  }
  tags = { project = "infrachat", layer = "core" }
}
