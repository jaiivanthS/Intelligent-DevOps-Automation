output "aws_region" {
  value = var.aws_region
}

output "jenkins_public_ip" {
  value = aws_eip.host["jenkins"].public_ip
}

output "app_public_ip" {
  value = aws_eip.host["app"].public_ip
}

output "app_private_ip" {
  description = "Used by Jenkins to deploy over the VPC network."
  value       = aws_instance.host["app"].private_ip
}

output "jenkins_private_ip" {
  value = aws_instance.host["jenkins"].private_ip
}

output "jenkins_url" {
  value = "http://${aws_eip.host["jenkins"].public_ip}:8080"
}

output "github_webhook_url" {
  description = "Paste into GitHub > Settings > Webhooks (content type application/json)."
  value       = "http://${aws_eip.host["jenkins"].public_ip}:8080/github-webhook/"
}

output "app_url" {
  value = "http://${aws_eip.host["app"].public_ip}"
}

output "grafana_url" {
  value = "http://${aws_eip.host["app"].public_ip}:3000"
}

output "platform_url" {
  value = "http://${aws_eip.host["app"].public_ip}:8081"
}

output "ecr_registry" {
  value = local.ecr_registry
}

output "ecr_repository_url" {
  value = aws_ecr_repository.demo_app.repository_url
}

output "ssh_jenkins" {
  value = "ssh ubuntu@${aws_eip.host["jenkins"].public_ip}"
}

output "ssh_app" {
  value = "ssh ubuntu@${aws_eip.host["app"].public_ip}"
}
