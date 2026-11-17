# Baked AMI: AL2023 + Docker + the StreamLite image pre-pulled + a *disabled* systemd unit (F9).
# Build with `make ami`, which passes the image tag and writes infra/ami.auto.tfvars.

packer {
  required_plugins {
    amazon = {
      source  = "github.com/hashicorp/amazon"
      version = ">= 1.3.0"
    }
  }
}

variable "image" {
  description = "Full image reference, e.g. ghcr.io/<owner>/streamlite:<sha7>"
  type        = string
}

variable "tag" {
  description = "Image tag (git sha7), used in the AMI name and tags"
  type        = string
}

variable "region" {
  type    = string
  default = "ap-south-1"
}

variable "instance_type" {
  # Free-plan eligible. The AMI is plain x86_64 AL2023, so it also runs on any other x86 type.
  type    = string
  default = "c7i-flex.large"
}

source "amazon-ebs" "al2023" {
  region        = var.region
  instance_type = var.instance_type
  ssh_username  = "ec2-user"
  ami_name      = "hsl-streamlite-${var.tag}-{{timestamp}}"
  imds_support  = "v2.0"

  source_ami_filter {
    filters = {
      name                = "al2023-ami-2023.*-x86_64"
      virtualization-type = "hvm"
      root-device-type    = "ebs"
    }
    owners      = ["amazon"]
    most_recent = true
  }

  # Fix F17: the temporary SG opens 22 only to this machine's public IP and is deleted afterwards.
  temporary_security_group_source_public_ip = true
  associate_public_ip_address               = true

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 2
  }

  tags = {
    Name       = "hsl-streamlite-${var.tag}"
    project    = "hotstar-scale-lab"
    managed_by = "packer"
    git_sha    = var.tag
    image      = var.image
  }
  snapshot_tags = {
    project = "hotstar-scale-lab"
    git_sha = var.tag
  }
  run_tags = {
    Name    = "hsl-packer-builder"
    project = "hotstar-scale-lab"
  }
}

build {
  sources = ["source.amazon-ebs.al2023"]

  provisioner "shell" {
    script           = "${path.root}/provision.sh"
    environment_vars = ["IMAGE=${var.image}"]
    # {{ .Vars }} is what injects environment_vars; without it IMAGE is empty in the script.
    execute_command = "chmod +x '{{ .Path }}'; sudo env {{ .Vars }} bash '{{ .Path }}'"
  }

  post-processor "manifest" {
    output     = "${path.root}/manifest.json"
    strip_path = true
  }
}
