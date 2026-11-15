# Offline tests: `make tf-test` (terraform test). Mock providers, so no AWS account,
# credentials or cost; "apply" here only runs against the mocks.

mock_provider "aws" {
  mock_data "aws_caller_identity" {
    defaults = { account_id = "123456789012" }
  }
  mock_data "aws_subnets" {
    defaults = { ids = ["subnet-0aaa", "subnet-0bbb", "subnet-0ccc"] }
  }
  mock_data "aws_ssm_parameter" {
    defaults = { value = "ami-0a12023stock0000" }
  }
  mock_data "aws_iam_policy_document" {
    defaults = { json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}" }
  }
  mock_resource "aws_lb" {
    defaults = {
      arn        = "arn:aws:elasticloadbalancing:ap-south-1:123456789012:loadbalancer/app/hsl-alb/50dc6c495c0c9188"
      arn_suffix = "app/hsl-alb/50dc6c495c0c9188"
      dns_name   = "hsl-alb-123.ap-south-1.elb.amazonaws.com"
    }
  }
  mock_resource "aws_lb_target_group" {
    defaults = {
      arn        = "arn:aws:elasticloadbalancing:ap-south-1:123456789012:targetgroup/hsl-tg/73e2d6bc24d8a067"
      arn_suffix = "targetgroup/hsl-tg/73e2d6bc24d8a067"
    }
  }
  mock_resource "aws_lb_listener" {
    defaults = { arn = "arn:aws:elasticloadbalancing:ap-south-1:123456789012:listener/app/hsl-alb/50dc6c495c0c9188/f2f7dc8efc522ab2" }
  }
  mock_resource "aws_cloudfront_distribution" {
    defaults = {
      arn         = "arn:aws:cloudfront::123456789012:distribution/E2EXAMPLE"
      domain_name = "d111111abcdef8.cloudfront.net"
    }
  }
  mock_resource "aws_s3_bucket" {
    defaults = { arn = "arn:aws:s3:::hsl-bucket-test01" }
  }
  mock_resource "aws_autoscaling_group" {
    defaults = { arn = "arn:aws:autoscaling:ap-south-1:123456789012:autoScalingGroup:uuid:autoScalingGroupName/hsl-asg" }
  }
  mock_resource "aws_launch_template" {
    defaults = { id = "lt-0123456789abcdef0", latest_version = 1 }
  }
  mock_resource "aws_security_group" {
    defaults = { id = "sg-0123456789abcdef0" }
  }
  mock_resource "aws_iam_role" {
    defaults = { arn = "arn:aws:iam::123456789012:role/hsl-role" }
  }
}

mock_provider "random" {}


variables {
  suffix = "test01"
  ami_id = "ami-0baked000000000001"
}

run "baked_demo_stack" {
  command = apply

  # F3: Indian edge locations
  assert {
    condition     = aws_cloudfront_distribution.main.price_class == "PriceClass_200"
    error_message = "CloudFront must use PriceClass_200"
  }
  # behaviour order: the cached match path must win over /api/*
  assert {
    condition = [for b in aws_cloudfront_distribution.main.ordered_cache_behavior : b.path_pattern] == [
      "/api/v1/match/*", "/api/*"
    ]
    error_message = "ordered behaviours must be /api/v1/match/* then /api/*"
  }
  assert {
    condition     = aws_cloudfront_distribution.main.ordered_cache_behavior[1].origin_request_policy_id == "b689b0a8-53d0-40ab-baf2-68738e2966ac"
    error_message = "/api/* must forward viewer headers (X-Forwarded-For for the rate limiter)"
  }
  assert {
    condition = [for b in aws_cloudfront_distribution.main.ordered_cache_behavior : b.cache_policy_id] == [
      "658327ea-f89d-4fab-a63d-7e88639e58f6", "4135ea2d-6df8-44a3-9df3-4b5a84be39ad"
    ]
    error_message = "match state is cached (CachingOptimized), the rest of /api/* is not (CachingDisabled)"
  }
  # F2: /internal/* blocked at the ALB with the highest priority
  assert {
    condition = (
      aws_lb_listener_rule.block_internal.priority == 1 &&
      aws_lb_listener_rule.block_internal.action[0].fixed_response[0].status_code == "404" &&
      contains(flatten([for c in aws_lb_listener_rule.block_internal.condition : [for p in c.path_pattern : p.values]]), "/internal/*")
    )
    error_message = "/internal/* must return a fixed 404 at priority 1"
  }
  # F16 + IMDSv2
  assert {
    condition = (
      aws_launch_template.app.metadata_options[0].http_tokens == "required" &&
      aws_launch_template.app.metadata_options[0].http_put_response_hop_limit == 2
    )
    error_message = "launch template must require IMDSv2 with hop limit 2"
  }
  # baked mode: the AMI from `make ami`, env file before the service starts (F9)
  assert {
    condition     = aws_launch_template.app.image_id == "ami-0baked000000000001"
    error_message = "baked mode must use var.ami_id"
  }
  assert {
    condition = (
      strcontains(base64decode(aws_launch_template.app.user_data), "WORK_SCALE=2.0") &&
      strcontains(base64decode(aws_launch_template.app.user_data), "systemctl enable --now streamlite") &&
      !strcontains(base64decode(aws_launch_template.app.user_data), "loadtest_token")
    )
    error_message = "baked user_data must write the env file, start the service and never contain the token"
  }
  assert {
    condition     = aws_autoscaling_group.app.health_check_grace_period == 60 && aws_autoscaling_group.app.max_size == 6
    error_message = "baked ASG: grace 60 s, max 6"
  }
  # F10: token is a SecureString
  assert {
    condition     = aws_ssm_parameter.token.type == "SecureString"
    error_message = "load-test token must be a SecureString"
  }
  # no port 22 anywhere
  assert {
    condition = alltrue([
      for r in [aws_vpc_security_group_ingress_rule.alb_http, aws_vpc_security_group_ingress_rule.app_from_alb,
      aws_vpc_security_group_ingress_rule.app_from_loadgen] : r.from_port > 22 || r.to_port < 22
    ])
    error_message = "no ingress rule may cover port 22"
  }
  # idle stack: no loadgen, no TF budget without emails
  assert {
    condition     = length(aws_instance.loadgen) == 0 && length(aws_budgets_budget.monthly) == 0
    error_message = "loadgen and budget must be off by default"
  }
  assert {
    condition     = output.cloudfront_url == "https://d111111abcdef8.cloudfront.net" && output.loadgen_instance_id == ""
    error_message = "outputs"
  }
}

run "baked_requires_ami" {
  command = plan
  variables { ami_id = "" }
  expect_failures = [aws_launch_template.app]
}

run "naive_boot" {
  command = apply
  variables {
    user_data_mode = "naive"
    ami_id         = ""
    image          = "ghcr.io/yug1707/streamlite:86c00d4"
  }

  assert {
    condition     = aws_launch_template.app.image_id == "ami-0a12023stock0000"
    error_message = "naive mode must use the stock AL2023 AMI"
  }
  assert {
    condition     = strcontains(base64decode(aws_launch_template.app.user_data), "docker pull ghcr.io/yug1707/streamlite:86c00d4")
    error_message = "naive user_data must pull the image at boot"
  }
  assert {
    condition     = aws_autoscaling_group.app.health_check_grace_period == 240
    error_message = "naive mode needs a 240 s grace period"
  }
}

run "naive_requires_image" {
  command = plan
  variables {
    user_data_mode = "naive"
    image          = "streamlite:latest"
  }
  expect_failures = [aws_launch_template.app]
}

run "asg_max_capped_at_6" {
  command = plan
  variables { asg_max = 7 }
  expect_failures = [var.asg_max]
}

run "lab_session" {
  command = apply
  variables {
    enable_loadgen = true
    alert_emails   = ["member-a@example.com"]
  }

  assert {
    condition     = length(aws_instance.loadgen) == 1 && aws_instance.loadgen[0].instance_type == "c6i.xlarge"
    error_message = "lab-up must create one c6i.xlarge loadgen"
  }
  assert {
    condition = (
      strcontains(aws_instance.loadgen[0].user_data, "k6-v1.8.3-linux-amd64") &&
      strcontains(aws_instance.loadgen[0].user_data, "export ASG_NAME=hsl-asg") &&
      strcontains(aws_instance.loadgen[0].user_data, "export CLOUDFRONT_URL=https://d111111abcdef8.cloudfront.net")
    )
    error_message = "loadgen user_data must install k6 and export the stack names"
  }
  assert {
    condition     = length(aws_budgets_budget.monthly) == 1
    error_message = "budget must exist when emails are given"
  }
}
