# Runtime switches read by the app (degrade poller, load-test token) and written by the harness.

resource "aws_ssm_parameter" "degrade" {
  name        = "/streamlite/degrade_level"
  description = "0 = normal, 1 = non-critical endpoints return the cheap fallback (E6)"
  type        = "String"
  value       = "0"

  lifecycle {
    ignore_changes = [value] # experiments flip it; Terraform must not reset it
  }
}

# Load-test bypass token (fix F10): never in user_data, tfvars or Git.
resource "random_password" "token" {
  length  = 32
  special = false
}

resource "aws_ssm_parameter" "token" {
  name        = "/streamlite/loadtest_token"
  description = "X-Load-Test header value that bypasses the public rate limit"
  type        = "SecureString"
  value       = random_password.token.result
}
