variable "region" {
  type    = string
  default = "ap-south-1"
}

variable "suffix" {
  description = "Random suffix that makes bucket names globally unique (e.g. `openssl rand -hex 3`)."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9-]{3,20}$", var.suffix))
    error_message = "suffix must be 3-20 chars of a-z, 0-9 or '-'."
  }
}

variable "owner" {
  description = "Team name for the owner tag."
  type        = string
  default     = "it457-team"
}

# ---- application fleet -------------------------------------------------------------------------
variable "user_data_mode" {
  description = "baked = Packer AMI with the image pre-pulled; naive = stock AL2023 that installs Docker and pulls at boot (E5)."
  type        = string
  default     = "baked"

  validation {
    condition     = contains(["baked", "naive"], var.user_data_mode)
    error_message = "user_data_mode must be baked or naive."
  }
}

variable "ami_id" {
  description = "Baked AMI from `make ami` (written to ami.auto.tfvars). Required when user_data_mode = baked."
  type        = string
  default     = ""
}

variable "image" {
  description = "Full container image reference, e.g. ghcr.io/<owner>/streamlite:<sha7>. Used by naive mode."
  type        = string
  default     = ""
}

variable "instance_type" {
  description = "App instance type. c7i-flex.large (2 vCPU, 4 GiB) is allowed on the AWS Free plan; c6i.large is not."
  type        = string
  default     = "c7i-flex.large"
}

variable "asg_min" {
  type    = number
  default = 1
}

variable "asg_max" {
  type    = number
  default = 4

  validation {
    condition     = var.asg_max >= 1 && var.asg_max <= 4
    error_message = "asg_max is capped at 4 (Free plan: USD 118 credit and a small vCPU quota)."
  }
}

variable "asg_desired" {
  type    = number
  default = 1
}

variable "work_scale" {
  description = "CPU cost multiplier for the app; set from the c7i-flex.large calibration (T2.7)."
  type        = string
  default     = "2.0"
}

variable "web_concurrency" {
  description = "uvicorn worker processes per instance (2 only if E1 shows GIL contention)."
  type        = number
  default     = 1
}

variable "enable_cloudfront" {
  description = <<-EOT
    Create the CloudFront distribution (HTTPS URL, dashboard, E7). New AWS accounts get
    "Your account must be verified before you can add new CloudFront resources" until AWS Support
    verifies them; with false the stack runs without it and the public URL is the ALB (HTTP, API only).
  EOT
  type        = bool
  default     = true
}

# ---- lab -------------------------------------------------------------------------------------
variable "enable_loadgen" {
  description = "Create the k6 load-generator instance. Keep false outside lab sessions."
  type        = bool
  default     = false
}

variable "loadgen_instance_type" {
  description = "k6 load generator. 2 vCPU is enough for the scaled-down peak (2.8 x C1); runs are invalid above 70 % CPU."
  type        = string
  default     = "c7i-flex.large"
}

variable "k6_version" {
  type    = string
  default = "1.8.3"
}

variable "force_destroy_results" {
  description = "Allow `terraform destroy` to delete the results bucket with data in it. Set true only after the viva."
  type        = bool
  default     = false
}

# ---- cost guardrails -------------------------------------------------------------------------
variable "budget_usd" {
  description = "Monthly alarm on gross usage (credits not subtracted). Total credit available: USD 118."
  type        = number
  default     = 25
}

variable "alert_emails" {
  description = "Budget alert recipients. Empty list = no Terraform budget (the manual one from T0.3 still exists)."
  type        = list(string)
  default     = []
}
