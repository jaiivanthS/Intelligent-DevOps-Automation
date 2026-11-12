# Port map
#   Jenkins host : 22 SSH (admin), 8080 Jenkins UI (admin + GitHub webhooks),
#                  9100 node-exporter (from app host's Prometheus)
#   App host     : 22 SSH (admin + Jenkins deploys), 80 demo app (public + Jenkins smoke tests),
#                  3000 Grafana, 9090 Prometheus, 8000 platform API, 8081 platform UI (admin)
#   Loki (3100) and Alertmanager (9093) stay internal to the app host's Docker network.

resource "aws_security_group" "jenkins" {
  name        = "${local.name}-jenkins"
  description = "Jenkins CI/CD host"
  vpc_id      = aws_vpc.main.id
  tags        = { Name = "${local.name}-jenkins" }
}

resource "aws_security_group" "app" {
  name        = "${local.name}-app"
  description = "Application and monitoring host"
  vpc_id      = aws_vpc.main.id
  tags        = { Name = "${local.name}-app" }
}

# ---------------------------------------------------------------- Jenkins host
resource "aws_vpc_security_group_ingress_rule" "jenkins_ssh_admin" {
  for_each          = toset(var.admin_cidrs)
  security_group_id = aws_security_group.jenkins.id
  description       = "SSH from admin"
  cidr_ipv4         = each.value
  ip_protocol       = "tcp"
  from_port         = 22
  to_port           = 22
}

resource "aws_vpc_security_group_ingress_rule" "jenkins_ui_admin" {
  for_each          = toset(var.admin_cidrs)
  security_group_id = aws_security_group.jenkins.id
  description       = "Jenkins UI from admin"
  cidr_ipv4         = each.value
  ip_protocol       = "tcp"
  from_port         = 8080
  to_port           = 8080
}

resource "aws_vpc_security_group_ingress_rule" "jenkins_webhooks" {
  for_each          = toset(var.github_webhook_cidrs)
  security_group_id = aws_security_group.jenkins.id
  description       = "GitHub webhooks"
  cidr_ipv4         = each.value
  ip_protocol       = "tcp"
  from_port         = 8080
  to_port           = 8080
}

resource "aws_vpc_security_group_ingress_rule" "jenkins_from_app" {
  for_each = {
    jenkins_metrics = 8080 # Prometheus scrapes /prometheus; platform API calls the Jenkins API
    node_exporter   = 9100
  }
  security_group_id            = aws_security_group.jenkins.id
  description                  = "${each.key} from app host"
  referenced_security_group_id = aws_security_group.app.id
  ip_protocol                  = "tcp"
  from_port                    = each.value
  to_port                      = each.value
}

resource "aws_vpc_security_group_egress_rule" "jenkins_all" {
  security_group_id = aws_security_group.jenkins.id
  description       = "Outbound (GitHub, ECR, package mirrors, deploy to app host)"
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
}

# -------------------------------------------------------------------- App host
resource "aws_vpc_security_group_ingress_rule" "app_ssh_admin" {
  for_each          = toset(var.admin_cidrs)
  security_group_id = aws_security_group.app.id
  description       = "SSH from admin"
  cidr_ipv4         = each.value
  ip_protocol       = "tcp"
  from_port         = 22
  to_port           = 22
}

resource "aws_vpc_security_group_ingress_rule" "app_from_jenkins" {
  for_each = {
    ssh_deploy  = 22
    smoke_tests = 80
  }
  security_group_id            = aws_security_group.app.id
  description                  = "${each.key} from Jenkins"
  referenced_security_group_id = aws_security_group.jenkins.id
  ip_protocol                  = "tcp"
  from_port                    = each.value
  to_port                      = each.value
}

resource "aws_vpc_security_group_ingress_rule" "app_http" {
  for_each          = toset(var.app_ingress_cidrs)
  security_group_id = aws_security_group.app.id
  description       = "Demo application"
  cidr_ipv4         = each.value
  ip_protocol       = "tcp"
  from_port         = 80
  to_port           = 80
}

locals {
  app_admin_ports = {
    grafana     = 3000
    prometheus  = 9090
    platformapi = 8000
    platformui  = 8081
  }

  app_admin_rules = {
    for pair in setproduct(keys(local.app_admin_ports), var.admin_cidrs) :
    "${pair[0]}-${pair[1]}" => { port = local.app_admin_ports[pair[0]], cidr = pair[1], name = pair[0] }
  }
}

resource "aws_vpc_security_group_ingress_rule" "app_admin_ui" {
  for_each          = local.app_admin_rules
  security_group_id = aws_security_group.app.id
  description       = "${each.value.name} from admin"
  cidr_ipv4         = each.value.cidr
  ip_protocol       = "tcp"
  from_port         = each.value.port
  to_port           = each.value.port
}

resource "aws_vpc_security_group_egress_rule" "app_all" {
  security_group_id = aws_security_group.app.id
  description       = "Outbound (ECR pulls, package mirrors, Jenkins API)"
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
}
