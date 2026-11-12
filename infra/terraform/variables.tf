variable "project_name" {
  description = "Prefix for resource names and the Project tag."
  type        = string
  default     = "devops-platform"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,24}$", var.project_name))
    error_message = "Use 3-25 lowercase letters, digits or hyphens, starting with a letter."
  }
}

variable "environment" {
  description = "Environment name (e.g. dev, staging)."
  type        = string
  default     = "dev"
}

variable "aws_region" {
  description = "AWS region to deploy into."
  type        = string
  default     = "ap-south-1"
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC."
  type        = string
  default     = "10.20.0.0/16"
}

variable "public_subnet_cidr" {
  description = "CIDR block for the public subnet hosting both instances."
  type        = string
  default     = "10.20.1.0/24"
}

variable "admin_cidrs" {
  description = "CIDRs allowed to reach SSH and admin UIs (Jenkins, Grafana, Prometheus, platform). Use your public IP as x.x.x.x/32."
  type        = list(string)

  validation {
    condition     = length(var.admin_cidrs) > 0 && alltrue([for c in var.admin_cidrs : can(cidrhost(c, 0))])
    error_message = "Provide at least one valid CIDR, e.g. [\"203.0.113.10/32\"]."
  }

  validation {
    condition     = !contains(var.admin_cidrs, "0.0.0.0/0")
    error_message = "Do not open admin ports to the whole internet; use your own IP /32."
  }
}

variable "app_ingress_cidrs" {
  description = "CIDRs allowed to reach the demo application on port 80."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "github_webhook_cidrs" {
  description = "GitHub webhook source ranges (https://api.github.com/meta, \"hooks\") allowed to reach Jenkins on 8080."
  type        = list(string)
  default     = ["192.30.252.0/22", "185.199.108.0/22", "140.82.112.0/20", "143.55.64.0/20"]
}

variable "ssh_public_key" {
  description = "Public key (contents of ~/.ssh/id_ed25519.pub) installed on both instances."
  type        = string

  validation {
    condition     = can(regex("^(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp256) ", var.ssh_public_key))
    error_message = "Must be an OpenSSH public key (ssh-ed25519 / ssh-rsa / ecdsa)."
  }
}

variable "jenkins_instance_type" {
  description = "Instance type for the Jenkins host (Jenkins needs at least 2 GB RAM)."
  type        = string
  default     = "t3.medium"
}

variable "app_instance_type" {
  description = "Instance type for the application + monitoring host."
  type        = string
  default     = "t3.medium"
}

variable "jenkins_volume_gb" {
  description = "Root volume size for the Jenkins host (workspaces and Docker images)."
  type        = number
  default     = 30
}

variable "app_volume_gb" {
  description = "Root volume size for the application host (images, metrics, logs)."
  type        = number
  default     = 30
}

variable "enable_ssm" {
  description = "Attach AmazonSSMManagedInstanceCore so instances can be reached with Session Manager instead of SSH."
  type        = bool
  default     = true
}

variable "ecr_image_retention" {
  description = "Number of most recent images kept in ECR (older ones expire; keep enough for rollback)."
  type        = number
  default     = 20
}
