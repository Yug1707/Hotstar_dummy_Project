# Results bucket (always on, cheap) and the k6 load generator (only during lab sessions:
# `make lab-up` creates it, `make destroy-lab` removes it).

resource "aws_s3_bucket" "results" {
  bucket        = "${local.name}-results-${var.suffix}"
  force_destroy = var.force_destroy_results
}

resource "aws_s3_bucket_public_access_block" "results" {
  bucket                  = aws_s3_bucket.results.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "results" {
  bucket = aws_s3_bucket.results.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "results" {
  bucket = aws_s3_bucket.results.id

  rule {
    id     = "expire-harness-tarballs"
    status = "Enabled"
    filter {
      prefix = "harness/"
    }
    expiration {
      days = 30
    }
  }
}

resource "aws_instance" "loadgen" {
  count = var.enable_loadgen ? 1 : 0

  ami                         = nonsensitive(data.aws_ssm_parameter.al2023.value)
  instance_type               = var.loadgen_instance_type
  subnet_id                   = sort(data.aws_subnets.default.ids)[0]
  vpc_security_group_ids      = [aws_security_group.loadgen.id]
  iam_instance_profile        = aws_iam_instance_profile.loadgen.name
  associate_public_ip_address = true
  monitoring                  = true

  user_data = templatefile("${path.module}/user_data_loadgen.sh.tftpl", {
    k6_version     = var.k6_version
    region         = var.region
    results_bucket = aws_s3_bucket.results.bucket
    asg_name       = aws_autoscaling_group.app.name
    tg_arn         = aws_lb_target_group.app.arn
    tg_arn_suffix  = aws_lb_target_group.app.arn_suffix
    alb_arn_suffix = aws_lb.app.arn_suffix
    alb_dns        = aws_lb.app.dns_name
    cloudfront_url = "https://${aws_cloudfront_distribution.main.domain_name}"
  })
  user_data_replace_on_change = true

  root_block_device {
    volume_type = "gp3"
    volume_size = 30
    encrypted   = true
  }

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 2
  }

  tags = { Name = "${local.name}-loadgen" }

  lifecycle {
    ignore_changes = [ami] # a newer AL2023 must not replace the loadgen mid-session
  }
}
