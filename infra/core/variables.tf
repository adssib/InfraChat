variable "subscription_id" {
  description = "Azure for Students. Never the Concordia production subscription."
  type        = string
  default     = "2b812a74-f9f4-4848-b71d-eb7898148ce3"
}

variable "location" {
  # Azure for Students only allows francecentral, northcentralus, norwayeast, westus and
  # canadacentral (a subscription policy; eastus is refused with RequestDisallowedByAzure).
  # canadacentral: nearest to the developer, and Groq served this account from Montreal.
  type    = string
  default = "canadacentral"
}

variable "github_repo" {
  description = "The repository whose master-branch workflows may log in, as GitHub writes it in the OIDC subject: owner@owner_id/repo@repo_id."
  type        = string
  default     = "adssib@75389300/InfraChat@1351873446"
}
