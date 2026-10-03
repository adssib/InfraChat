output "environment_id" {
  value = azurerm_container_app_environment.env.id
}

output "default_domain" {
  description = "The app will live at https://infrachat-api.<this>."
  value       = azurerm_container_app_environment.env.default_domain
}
