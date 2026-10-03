variable "subscription_id" {
  description = "Azure for Students. Never the Concordia production subscription."
  type        = string
  default     = "2b812a74-f9f4-4848-b71d-eb7898148ce3"
}

variable "location" {
  type    = string
  default = "eastus"
}
