output "environment_id" {
  value = azurerm_container_app_environment.env.id
}

output "default_domain" {
  description = "The app will live at https://infrachat-api.<this>."
  value       = azurerm_container_app_environment.env.default_domain
}

# Not secrets: the workflow needs these as plain repository variables.
output "azure_client_id" {
  value = azurerm_user_assigned_identity.github.client_id
}

output "azure_tenant_id" {
  value = data.azurerm_client_config.current.tenant_id
}
