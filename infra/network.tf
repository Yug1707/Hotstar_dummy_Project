# Default VPC and its default subnets (one per AZ). No NAT gateway, no port 22 anywhere:
# shell access is through SSM Session Manager only.

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
  filter {
    name   = "default-for-az"
    values = ["true"]
  }
}

# Not every AZ offers every instance type. The ASG and the loadgen use only the default subnets in AZs
# that offer both instance types; the ALB keeps all default subnets (it routes across zones).
data "aws_ec2_instance_type_offerings" "compute" {
  location_type = "availability-zone"
  filter {
    name   = "instance-type"
    values = [var.instance_type]
  }
}

data "aws_subnets" "compute" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
  filter {
    name   = "default-for-az"
    values = ["true"]
  }
  filter {
    name   = "availability-zone"
    values = data.aws_ec2_instance_type_offerings.compute.locations
  }
}

resource "aws_security_group" "alb" {
  name        = "${local.name}-alb-sg"
  description = "ALB: HTTP from anywhere (CloudFront and loadgen)"
  vpc_id      = data.aws_vpc.default.id
  tags        = { Name = "${local.name}-alb-sg" }
}

resource "aws_security_group" "app" {
  name        = "${local.name}-app-sg"
  description = "App instances: 8000 from the ALB and from loadgen (internal stats)"
  vpc_id      = data.aws_vpc.default.id
  tags        = { Name = "${local.name}-app-sg" }
}

resource "aws_security_group" "loadgen" {
  name        = "${local.name}-loadgen-sg"
  description = "Load generator: no ingress"
  vpc_id      = data.aws_vpc.default.id
  tags        = { Name = "${local.name}-loadgen-sg" }
}

# ---- ALB ---------------------------------------------------------------------------------------
resource "aws_vpc_security_group_ingress_rule" "alb_http" {
  security_group_id = aws_security_group.alb.id
  description       = "HTTP from anywhere"
  ip_protocol       = "tcp"
  from_port         = 80
  to_port           = 80
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_vpc_security_group_egress_rule" "alb_to_app" {
  security_group_id            = aws_security_group.alb.id
  description                  = "Forward to app port"
  ip_protocol                  = "tcp"
  from_port                    = 8000
  to_port                      = 8000
  referenced_security_group_id = aws_security_group.app.id
}

# ---- app ---------------------------------------------------------------------------------------
resource "aws_vpc_security_group_ingress_rule" "app_from_alb" {
  security_group_id            = aws_security_group.app.id
  description                  = "Traffic and health checks from the ALB"
  ip_protocol                  = "tcp"
  from_port                    = 8000
  to_port                      = 8000
  referenced_security_group_id = aws_security_group.alb.id
}

resource "aws_vpc_security_group_ingress_rule" "app_from_loadgen" {
  security_group_id            = aws_security_group.app.id
  description                  = "Proactive scaler reads /internal/stats on the private IP"
  ip_protocol                  = "tcp"
  from_port                    = 8000
  to_port                      = 8000
  referenced_security_group_id = aws_security_group.loadgen.id
}

resource "aws_vpc_security_group_egress_rule" "app_all" {
  security_group_id = aws_security_group.app.id
  description       = "GHCR, SSM, S3"
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"
}

# ---- loadgen -----------------------------------------------------------------------------------
resource "aws_vpc_security_group_egress_rule" "loadgen_all" {
  security_group_id = aws_security_group.loadgen.id
  description       = "ALB, app private IPs, AWS APIs, GitHub (k6 download)"
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"
}
