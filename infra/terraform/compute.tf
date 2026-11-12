data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"] # Canonical

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

resource "aws_key_pair" "admin" {
  key_name   = "${local.name}-admin"
  public_key = var.ssh_public_key
}

locals {
  ecr_registry = split("/", aws_ecr_repository.demo_app.repository_url)[0]

  hosts = {
    jenkins = {
      instance_type    = var.jenkins_instance_type
      volume_gb        = var.jenkins_volume_gb
      security_group   = aws_security_group.jenkins.id
      instance_profile = aws_iam_instance_profile.jenkins.name
      workdir          = "jenkins"
    }
    app = {
      instance_type    = var.app_instance_type
      volume_gb        = var.app_volume_gb
      security_group   = aws_security_group.app.id
      instance_profile = aws_iam_instance_profile.app.name
      workdir          = "app"
    }
  }
}

resource "aws_instance" "host" {
  for_each = local.hosts

  ami                    = data.aws_ami.ubuntu.id
  instance_type          = each.value.instance_type
  subnet_id              = aws_subnet.public.id
  vpc_security_group_ids = [each.value.security_group]
  iam_instance_profile   = each.value.instance_profile
  key_name               = aws_key_pair.admin.key_name

  user_data = templatefile("${path.module}/templates/bootstrap.sh.tftpl", {
    role           = each.key
    hostname       = "${local.name}-${each.key}"
    workdir        = each.value.workdir
    project        = var.project_name
    environment    = var.environment
    aws_region     = var.aws_region
    ecr_registry   = local.ecr_registry
    ecr_repository = aws_ecr_repository.demo_app.repository_url
  })

  # IMDSv2 only. Hop limit 2 lets containers (e.g. Jenkins in Docker) use the instance role.
  metadata_options {
    http_tokens                 = "required"
    http_put_response_hop_limit = 2
    http_endpoint               = "enabled"
  }

  root_block_device {
    volume_type           = "gp3"
    volume_size           = each.value.volume_gb
    encrypted             = true
    delete_on_termination = true
  }

  # "standard" avoids surprise charges from T3 unlimited burst mode.
  credit_specification {
    cpu_credits = "standard"
  }

  tags = { Name = "${local.name}-${each.key}", Role = each.key }

  lifecycle {
    # Don't rebuild the servers just because Canonical published a newer AMI.
    ignore_changes = [ami]
  }
}

# Stable public addresses for webhooks, SSH and bookmarks.
resource "aws_eip" "host" {
  for_each = aws_instance.host

  instance = each.value.id
  domain   = "vpc"
  tags     = { Name = "${local.name}-${each.key}-eip" }

  depends_on = [aws_internet_gateway.main]
}
