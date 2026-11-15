# `make env` writes these to .env.tf (git-ignored) as UPPER_CASE=value for scripts to source.

output "cloudfront_url" {
  value = "https://${aws_cloudfront_distribution.main.domain_name}"
}

output "cloudfront_id" {
  value = aws_cloudfront_distribution.main.id
}

output "alb_dns" {
  value = aws_lb.app.dns_name
}

output "alb_arn_suffix" {
  value = aws_lb.app.arn_suffix
}

output "asg_name" {
  value = aws_autoscaling_group.app.name
}

output "target_group_arn" {
  value = aws_lb_target_group.app.arn
}

output "tg_arn_suffix" {
  value = aws_lb_target_group.app.arn_suffix
}

output "loadgen_instance_id" {
  value = try(aws_instance.loadgen[0].id, "")
}

output "results_bucket" {
  value = aws_s3_bucket.results.bucket
}

output "site_bucket" {
  value = aws_s3_bucket.site.bucket
}

output "region" {
  value = var.region
}

output "user_data_mode" {
  value = var.user_data_mode
}

output "app_ami" {
  value = aws_launch_template.app.image_id
}
