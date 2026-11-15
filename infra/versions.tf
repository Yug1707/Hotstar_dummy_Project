# Terraform, providers and the shared S3 state (fix F7).
# The bucket name is not committed: `make tf-init` passes infra/.backend.hcl (see backend.hcl.example).

terraform {
  required_version = ">= 1.10" # native S3 lock file (use_lockfile)

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  backend "s3" {
    key          = "hsl/terraform.tfstate"
    region       = "ap-south-1"
    use_lockfile = true
    encrypt      = true
  }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = local.tags
  }
}

data "aws_caller_identity" "current" {}

locals {
  name       = "hsl"
  account_id = data.aws_caller_identity.current.account_id

  tags = {
    project    = "hotstar-scale-lab"
    owner      = var.owner
    managed_by = "terraform"
    course     = "IT457"
  }
}
