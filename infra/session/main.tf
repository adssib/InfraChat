# The disposable layer: the container app for one 15-minute session. Applied by the
# demo-up workflow with throwaway state; torn down with `az containerapp delete`, never
# `terraform destroy`, so the state never needs storing (docs/DEMO-PLAN.md § 4).

provider "azurerm" {
  features {}
  subscription_id = var.subscription_id
}

data "azurerm_container_app_environment" "env" {
  name                = "cae-infrachat"
  resource_group_name = "rg-infrachat"
}

resource "azurerm_container_app" "api" {
  name                         = "infrachat-api"
  container_app_environment_id = data.azurerm_container_app_environment.env.id
  resource_group_name          = "rg-infrachat"
  revision_mode                = "Single"
  # The sweeper deletes any app whose expires-at has passed, in case the workflow died.
  tags = { project = "infrachat", layer = "session", "expires-at" = var.expires_at }

  template {
    min_replicas = 1 # warm for the whole session: the demo shouldn't cold-start mid-question
    max_replicas = 1

    container {
      name   = "api"
      image  = var.image
      cpu    = 1
      memory = "2Gi"
    }
  }

  ingress {
    external_enabled = true
    target_port      = var.port
    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }
}
