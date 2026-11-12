resource "aws_ecr_repository" "demo_app" {
  name                 = "${var.project_name}/demo-app"
  image_tag_mutability = "IMMUTABLE" # a tag always means the same image, so rollback is exact
  force_delete         = true        # allow `terraform destroy` on a demo environment

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }
}

resource "aws_ecr_lifecycle_policy" "demo_app" {
  repository = aws_ecr_repository.demo_app.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last ${var.ecr_image_retention} images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = var.ecr_image_retention
      }
      action = { type = "expire" }
    }]
  })
}
