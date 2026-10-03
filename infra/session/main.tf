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

  # The Groq key: a Container App secret, exposed to the container as an env var. It is
  # never in the image, the repo or a log (CLAUDE.md § Ethics).
  secret {
    name  = "llm-api-key"
    value = var.llm_api_key
  }

  template {
    min_replicas = 1 # warm for the whole session: the demo shouldn't cold-start mid-question
    max_replicas = 1

    container {
      name   = "api"
      image  = "ghcr.io/adssib/infrachat-api:${var.image_tag}"
      cpu    = 1
      memory = "2Gi"

      env {
        name        = "INFRACHAT_LLM_API_KEY"
        secret_name = "llm-api-key"
      }
      env {
        name  = "INFRACHAT_CORS_ORIGINS" # only the Pages site may call this API
        value = "https://adssib.github.io"
      }
      env {
        name  = "EXPIRES_AT"
        value = var.expires_at
      }
      env {
        name  = "GIT_SHA"
        value = var.image_tag
      }
      env {
        name  = "INDEX_VERSION"
        value = var.index_version
      }

      # /healthz answers once the embedder is loaded and the index is open.
      startup_probe {
        transport               = "HTTP"
        port                    = 8000
        path                    = "/healthz"
        interval_seconds        = 2
        failure_count_threshold = 30
      }
      readiness_probe {
        transport = "HTTP"
        port      = 8000
        path      = "/healthz"
      }
    }
  }

  ingress {
    external_enabled = true
    target_port      = 8000
    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }
}
