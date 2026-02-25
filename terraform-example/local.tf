# 로컬 환경변수 지정
locals {
  project             = "upgrade-test"
  project_prefix      = "poc"
  domain_name         = var.domain_name                                # 클러스터에 기반이 되는 루트 도메인
  project_domain_name = "${local.project_prefix}.${local.domain_name}" # 프로젝트에서만 사용하는 도메인
  tags = {                                                             # 모든 리소스에 적용되는 전역 태그
    "terraform" = "true"
    "project"   = local.project
  }
}