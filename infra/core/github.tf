# How GitHub Actions logs in to Azure for the demo button — with no stored password.
#
# A user-assigned managed identity trusts GitHub's OIDC token for this one repository's
# master branch (workflow_dispatch and the scheduled sweeper both run there). Chosen over
# an Entra app registration because a university tenant can forbid students from creating
# app registrations; a managed identity is an ordinary resource in our own group.
#
# It may only touch rg-infrachat: Contributor on that group, nothing at subscription level.

resource "azurerm_user_assigned_identity" "github" {
  name                = "id-infrachat-github"
  location            = azurerm_resource_group.core.location
  resource_group_name = azurerm_resource_group.core.name
  tags                = { project = "infrachat", layer = "core" }
}

resource "azurerm_federated_identity_credential" "github_master" {
  name                      = "github-master"
  user_assigned_identity_id = azurerm_user_assigned_identity.github.id
  issuer                    = "https://token.actions.githubusercontent.com"
  subject                   = "repo:${var.github_repo}:ref:refs/heads/master"
  audience                  = ["api://AzureADTokenExchange"]
}

resource "azurerm_role_assignment" "github_rg" {
  scope                = azurerm_resource_group.core.id
  role_definition_name = "Contributor"
  principal_id         = azurerm_user_assigned_identity.github.principal_id
}

data "azurerm_client_config" "current" {}
