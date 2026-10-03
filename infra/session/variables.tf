variable "subscription_id" {
  type    = string
  default = "2b812a74-f9f4-4848-b71d-eb7898148ce3"
}

variable "image" {
  description = "M1 spike uses Microsoft's quickstart image; M2 switches to ghcr.io/adssib/infrachat-api."
  type        = string
  default     = "mcr.microsoft.com/k8se/quickstart:latest"
}

variable "port" {
  type    = number
  default = 80
}

variable "expires_at" {
  description = "RFC 3339 UTC, e.g. 2026-10-03T18:30:00Z. Read by the sweeper."
  type        = string
}
