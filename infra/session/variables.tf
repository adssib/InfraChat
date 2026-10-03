variable "subscription_id" {
  type    = string
  default = "2b812a74-f9f4-4848-b71d-eb7898148ce3"
}

variable "image_tag" {
  description = "A commit SHA tag of ghcr.io/adssib/infrachat-api, so a session states exactly which code it runs."
  type        = string
  default     = "55f52f84055eb24ee2036f3a5562ab1e610dfd99"
}

variable "index_version" {
  description = "The index Release baked into that image (CI_docker_build.yml INDEX_VERSION)."
  type        = string
  default     = "index-v1"
}

variable "llm_api_key" {
  description = "The Groq key. Set TF_VAR_llm_api_key; never put it in a file."
  type        = string
  sensitive   = true
}

variable "expires_at" {
  description = "RFC 3339 UTC, e.g. 2026-10-03T18:30:00Z. Read by the sweeper and shown in the UI."
  type        = string
}
