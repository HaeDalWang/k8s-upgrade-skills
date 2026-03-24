# 로컬 환경변수 지정
locals {
  project             = "upgrade-skill"
  project_prefix      = "poc"
  tags = {
    "terraform" = "true"
    "project"   = local.project
  }
}