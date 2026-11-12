data "aws_iam_policy_document" "ec2_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

# ECR login tokens cannot be scoped to a repository, so this one action needs "*".
data "aws_iam_policy_document" "ecr_auth" {
  statement {
    sid       = "EcrLogin"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }
}

# ------------------------------------------------------------- Jenkins: push
data "aws_iam_policy_document" "jenkins_ecr_push" {
  source_policy_documents = [data.aws_iam_policy_document.ecr_auth.json]

  statement {
    sid = "PushDemoApp"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:BatchGetImage",
      "ecr:GetDownloadUrlForLayer",
      "ecr:InitiateLayerUpload",
      "ecr:UploadLayerPart",
      "ecr:CompleteLayerUpload",
      "ecr:PutImage",
      "ecr:DescribeImages",
      "ecr:DescribeImageScanFindings",
      "ecr:ListImages",
    ]
    resources = [aws_ecr_repository.demo_app.arn]
  }
}

resource "aws_iam_role" "jenkins" {
  name               = "${local.name}-jenkins"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json
}

resource "aws_iam_role_policy" "jenkins_ecr" {
  name   = "ecr-push-demo-app"
  role   = aws_iam_role.jenkins.id
  policy = data.aws_iam_policy_document.jenkins_ecr_push.json
}

resource "aws_iam_instance_profile" "jenkins" {
  name = "${local.name}-jenkins"
  role = aws_iam_role.jenkins.name
}

# ------------------------------------------------------------ App host: pull
data "aws_iam_policy_document" "app_ecr_pull" {
  source_policy_documents = [data.aws_iam_policy_document.ecr_auth.json]

  statement {
    sid = "PullDemoApp"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:BatchGetImage",
      "ecr:GetDownloadUrlForLayer",
      "ecr:DescribeImages",
      "ecr:ListImages",
    ]
    resources = [aws_ecr_repository.demo_app.arn]
  }
}

resource "aws_iam_role" "app" {
  name               = "${local.name}-app"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json
}

resource "aws_iam_role_policy" "app_ecr" {
  name   = "ecr-pull-demo-app"
  role   = aws_iam_role.app.id
  policy = data.aws_iam_policy_document.app_ecr_pull.json
}

resource "aws_iam_instance_profile" "app" {
  name = "${local.name}-app"
  role = aws_iam_role.app.name
}

# ------------------------------------------- Optional Session Manager access
resource "aws_iam_role_policy_attachment" "ssm" {
  for_each   = var.enable_ssm ? { jenkins = aws_iam_role.jenkins.name, app = aws_iam_role.app.name } : {}
  role       = each.value
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}
