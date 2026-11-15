# Instance roles. App instances only read /streamlite/*; the loadgen drives experiments.

locals {
  ssm_param_arn = "arn:aws:ssm:${var.region}:${local.account_id}:parameter/streamlite/*"
}

data "aws_iam_policy_document" "ec2_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

# ---- app ---------------------------------------------------------------------------------------
resource "aws_iam_role" "app" {
  name               = "${local.name}-app-role"
  assume_role_policy = data.aws_iam_policy_document.ec2_trust.json
}

resource "aws_iam_role_policy_attachment" "app_ssm_core" {
  role       = aws_iam_role.app.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

data "aws_iam_policy_document" "app" {
  statement {
    sid       = "ReadStreamliteParams"
    actions   = ["ssm:GetParameter"]
    resources = [local.ssm_param_arn]
  }
}

resource "aws_iam_role_policy" "app" {
  name   = "streamlite-params"
  role   = aws_iam_role.app.id
  policy = data.aws_iam_policy_document.app.json
}

resource "aws_iam_instance_profile" "app" {
  name = "${local.name}-app-profile"
  role = aws_iam_role.app.name
}

# ---- loadgen -----------------------------------------------------------------------------------
resource "aws_iam_role" "loadgen" {
  name               = "${local.name}-loadgen-role"
  assume_role_policy = data.aws_iam_policy_document.ec2_trust.json
}

resource "aws_iam_role_policy_attachment" "loadgen_ssm_core" {
  role       = aws_iam_role.loadgen.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

data "aws_iam_policy_document" "loadgen" {
  statement {
    sid = "DescribeOnly" # Describe/Get calls cannot be scoped to a resource
    actions = [
      "autoscaling:DescribeAutoScalingGroups",
      "autoscaling:DescribeAutoScalingInstances",
      "autoscaling:DescribeScalingActivities",
      "autoscaling:DescribePolicies",
      "autoscaling:DescribeScheduledActions",
      "elasticloadbalancing:DescribeTargetHealth",
      "elasticloadbalancing:DescribeTargetGroups",
      "elasticloadbalancing:DescribeLoadBalancers",
      "ec2:DescribeInstances",
      "cloudwatch:GetMetricData",
      "cloudwatch:ListMetrics",
      "ssm:GetCommandInvocation",
    ]
    resources = ["*"]
  }

  statement {
    sid = "DriveTheAsg" # asg_mode.py, proactive_scaler.py, E4(d) scheduled action
    actions = [
      "autoscaling:SetDesiredCapacity",
      "autoscaling:UpdateAutoScalingGroup",
      "autoscaling:PutScalingPolicy",
      "autoscaling:DeletePolicy",
      "autoscaling:PutScheduledUpdateGroupAction",
      "autoscaling:DeleteScheduledAction",
    ]
    resources = [aws_autoscaling_group.app.arn]
  }

  statement {
    sid       = "StreamliteParams" # flip degrade_level (E6), read the load-test token
    actions   = ["ssm:GetParameter", "ssm:PutParameter"]
    resources = [local.ssm_param_arn]
  }

  statement {
    sid       = "BootLogOnAppInstances" # E5 reads /var/log/hsl-boot.log with send-command
    actions   = ["ssm:SendCommand"]
    resources = ["arn:aws:ec2:${var.region}:${local.account_id}:instance/*"]
    condition {
      test     = "StringEquals"
      variable = "ssm:resourceTag/project"
      values   = ["hotstar-scale-lab"]
    }
  }

  statement {
    sid       = "RunShellScriptDocument"
    actions   = ["ssm:SendCommand"]
    resources = ["arn:aws:ssm:${var.region}::document/AWS-RunShellScript"]
  }

  statement {
    sid       = "ResultsBucketList"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.results.arn]
  }

  statement {
    sid       = "ResultsBucketObjects"
    actions   = ["s3:GetObject", "s3:PutObject"]
    resources = ["${aws_s3_bucket.results.arn}/*"]
  }
}

resource "aws_iam_role_policy" "loadgen" {
  name   = "hsl-lab"
  role   = aws_iam_role.loadgen.id
  policy = data.aws_iam_policy_document.loadgen.json
}

resource "aws_iam_instance_profile" "loadgen" {
  name = "${local.name}-loadgen-profile"
  role = aws_iam_role.loadgen.name
}
