# Public ALB across the default subnets. Round robin on purpose: E1-E7 assume it.

resource "aws_lb" "app" {
  name               = "${local.name}-alb"
  load_balancer_type = "application"
  internal           = false
  security_groups    = [aws_security_group.alb.id]
  subnets            = data.aws_subnets.default.ids
  idle_timeout       = 30
}

resource "aws_lb_target_group" "app" {
  name                          = "${local.name}-tg"
  port                          = 8000
  protocol                      = "HTTP"
  vpc_id                        = data.aws_vpc.default.id
  deregistration_delay          = 30
  load_balancing_algorithm_type = "round_robin"

  health_check {
    path                = "/healthz"
    interval            = 5
    timeout             = 3
    healthy_threshold   = 2
    unhealthy_threshold = 2
    matcher             = "200"
  }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.app.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.app.arn
  }
}

# Fix F2: /internal/stats must never be reachable from the internet (CloudFront -> ALB).
# The scaler on the loadgen reads it directly on each instance's private IP.
resource "aws_lb_listener_rule" "block_internal" {
  listener_arn = aws_lb_listener.http.arn
  priority     = 1

  action {
    type = "fixed-response"
    fixed_response {
      content_type = "text/plain"
      status_code  = "404"
      message_body = "not found"
    }
  }

  condition {
    path_pattern {
      values = ["/internal/*"]
    }
  }
}
