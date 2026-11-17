# Launch template + Auto Scaling group. There is deliberately NO aws_autoscaling_policy here:
# scaling modes (static N, CPU target tracking, proactive) are applied at run time by
# automation/asg_mode.py (Phase 3), so Terraform must ignore capacity changes (fix F1).

data "aws_ssm_parameter" "al2023" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}

locals {
  app_tags = merge(local.tags, { Name = "${local.name}-app" })
}

resource "aws_launch_template" "app" {
  name_prefix            = "${local.name}-app-"
  image_id               = var.user_data_mode == "baked" ? var.ami_id : nonsensitive(data.aws_ssm_parameter.al2023.value)
  instance_type          = var.instance_type
  update_default_version = true

  iam_instance_profile {
    name = aws_iam_instance_profile.app.name
  }

  network_interfaces {
    associate_public_ip_address = true # default subnets, no NAT: needed for SSM, GHCR and S3
    security_groups             = [aws_security_group.app.id]
    delete_on_termination       = true
  }

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required" # IMDSv2 only
    http_put_response_hop_limit = 2          # fix F16 (containers on a bridge network)
  }

  monitoring {
    enabled = true # 1-minute EC2 metrics
  }

  # Only for a burstable fallback (t3/t4g): "unlimited" so a saturated instance is not throttled to
  # its 20-30 % baseline mid-experiment (that would fake a capacity limit). Costs extra only on t*.
  dynamic "credit_specification" {
    for_each = startswith(var.instance_type, "t") ? [1] : []
    content {
      cpu_credits = "unlimited"
    }
  }

  user_data = base64encode(templatefile("${path.module}/user_data_${var.user_data_mode}.sh.tftpl", {
    image           = var.image
    work_scale      = var.work_scale
    web_concurrency = var.web_concurrency
    region          = var.region
  }))

  tag_specifications {
    resource_type = "instance"
    tags          = local.app_tags
  }

  tag_specifications {
    resource_type = "volume"
    tags          = local.app_tags
  }

  lifecycle {
    precondition {
      condition     = var.user_data_mode == "naive" || startswith(var.ami_id, "ami-")
      error_message = "user_data_mode = baked needs ami_id (run `make ami`, which writes infra/ami.auto.tfvars)."
    }
    precondition {
      condition     = var.user_data_mode == "baked" || can(regex("^ghcr\\.io/[a-z0-9-]+/streamlite:[0-9a-f]{7,40}$", var.image))
      error_message = "user_data_mode = naive needs image = ghcr.io/<owner>/streamlite:<sha> (make passes it)."
    }
  }
}

resource "aws_autoscaling_group" "app" {
  name                      = "${local.name}-asg"
  min_size                  = var.asg_min
  max_size                  = var.asg_max
  desired_capacity          = var.asg_desired
  vpc_zone_identifier       = data.aws_subnets.compute.ids
  target_group_arns         = [aws_lb_target_group.app.arn]
  health_check_type         = "ELB"
  health_check_grace_period = var.user_data_mode == "baked" ? 60 : 240
  default_instance_warmup   = 60
  wait_for_capacity_timeout = "15m"

  metrics_granularity = "1Minute"
  enabled_metrics = [
    "GroupDesiredCapacity",
    "GroupInServiceInstances",
    "GroupPendingInstances",
    "GroupTotalInstances",
    "GroupTerminatingInstances",
  ]

  launch_template {
    id      = aws_launch_template.app.id
    version = aws_launch_template.app.latest_version
  }

  # A new AMI or user_data rolls the fleet without dropping below the current capacity.
  instance_refresh {
    strategy = "Rolling"
    preferences {
      min_healthy_percentage = 100
      max_healthy_percentage = 200
    }
  }

  lifecycle {
    ignore_changes = [desired_capacity, min_size, max_size] # fix F1
    precondition {
      condition     = length(data.aws_subnets.compute.ids) > 0
      error_message = "No default subnet is in an AZ that offers ${var.instance_type}. Pick another instance_type."
    }
  }
}
