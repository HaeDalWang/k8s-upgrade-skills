# 여러 오픈소스 솔루션들의 비밀번호를 저장한 Secrets Manager 조회
data "aws_secretsmanager_secret_version" "auth" {
  secret_id = "seungdo/auth"
}
########################################################
# ACM Certificate for Project Domain
########################################################
# ACM에 존재하는 루트 도메인 인증서 불러오기
data "aws_acm_certificate" "existing" {
  domain   = local.domain_name
  statuses = ["ISSUED"]
}

# 프로젝트에서만 사용하는 ACM 인증서 발급 요청
resource "aws_acm_certificate" "project" {
  domain_name       = "*.${local.project_domain_name}"
  validation_method = "DNS"
  lifecycle {
    create_before_destroy = true
  }
}
# 위에서 생성한 ACM 인증서 검증하는 DNS 레코드 생성
resource "aws_route53_record" "acm_validation_project_domain" {
  for_each = {
    for dvo in aws_acm_certificate.project.domain_validation_options : dvo.domain_name => {
      name   = dvo.resource_record_name
      record = dvo.resource_record_value
      type   = dvo.resource_record_type
    }
  }
  allow_overwrite = true
  name            = each.value.name
  records         = [each.value.record]
  ttl             = 60
  type            = each.value.type
  zone_id         = data.aws_route53_zone.this.zone_id
}
# 인증서 발급 상태
resource "aws_acm_certificate_validation" "project" {
  certificate_arn         = aws_acm_certificate.project.arn
  validation_record_fqdns = [for record in aws_route53_record.acm_validation_project_domain : record.fqdn]
}


########################################################
# 애플리케이션에 부여할 IAM 역할 (IRSA)
########################################################
# # EZL App Server
# module "application_irsa" {
#   source  = "terraform-aws-modules/iam/aws//modules/iam-role-for-service-accounts"
#   version = "6.2.3"

#   name            = "ezl-app-server-dev-role"
#   use_name_prefix = false
  
#   policies = {
#       secretmanager_access = "arn:aws:iam::aws:policy/AWSSecretsManagerClientReadOnlyAccess"
#       s3_full_access  = "arn:aws:iam::aws:policy/AmazonS3FullAccess"
#       ssm_full_access = "arn:aws:iam::aws:policy/AmazonSSMFullAccess"
#       sqs_full_access = "arn:aws:iam::aws:policy/AmazonSQSFullAccess"
#   }
#   oidc_providers = {
#     ezl-app-server = {
#       provider_arn = module.eks.oidc_provider_arn
#       namespace_service_accounts = [
#         "intgapp:app-server"
#       ]
#     }
#   }
# }