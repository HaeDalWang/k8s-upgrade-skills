# Q&A — 자주 묻는 질문

## 버전 업그레이드

### Q: 1.33에서 1.35로 한 번에 올릴 수 없나요?

Kubernetes는 마이너 버전 +1 단계 업그레이드만 공식 지원합니다. 1.33 → 1.35처럼 2단계를 건너뛰면 API 호환성 문제, Add-on 충돌, 노드 버전 skew 초과 등이 발생할 수 있습니다.

1.33 → 1.34 → 1.35 순서로 두 번 실행해 주세요. 각 단계마다 recipe.md의 `current_version`과 `target_version`을 업데이트하면 됩니다.
더욱 중요한 점은 2 Step 이상의 버전을 한개의 세션으로 진행 했을때 컨텍스트 제한 등으로 AI Agent가 중요 공지(Release Notes) 등 누락할 수 있어 배제합니다

---

## 사전 검증 실패

### Q: CRITICAL 실패가 나오면 어떻게 해야 하나요?

스킬은 CRITICAL 실패를 감지하고 구체적인 해결 방법을 제시하지만, 직접 수정하지는 않습니다. 사용자가 제시된 방법대로 해결한 후 다시 업그레이드를 요청하면 Phase 0부터 재검증합니다.
이는 사용자별 워크로드 배포 전략과 환경의 파편화가 심해 자동 수정 로직 구현에 제약이 있습니다 추후 SubAgent 등으로 helm repo, yaml 파싱 등 해결할 여지가 있으나 현재 버전으로는 아직입니다

예시:
- PDB `disruptionsAllowed=0` → PDB의 `maxUnavailable`을 1 이상으로 수정하거나 replica 수를 늘림
- PV AZ에 노드가 1개뿐 → 해당 AZ에 노드를 추가하거나, 워크로드를 노드가 충분한 AZ로 이동

### Q: PV가 특정 AZ에 바인딩되어 있는데 자동으로 옮겨주나요?

아닙니다. AWS EBS 등 블록 스토리지 PV는 생성 시 AZ가 고정됩니다. 스킬은 "해당 AZ에 노드가 부족하여 drain 후 재스케줄이 불가능하다"는 위험을 감지하고 보고하지만, PV 자체를 다른 AZ로 이동하지는 않습니다.

해결 방법:
- 해당 AZ에 노드를 추가 (IaC에서 노드를 다른 AZ에서 생성)
- 또는 StatefulSet + PVC를 삭제 후 노드가 충분한 AZ에서 재생성

---

## 플랫폼 및 IaC 지원

### Q: eksctl이나 CDK로 관리하는 EKS 클러스터도 지원하나요?

현재는 Terraform으로 관리하는 EKS 클러스터만 지원합니다. eksctl, CDK, Pulumi 등은 아직 Sub-Skill이 구현되지 않았습니다.

### Q: 온프레미스 Kubespray 클러스터는 언제 지원되나요?

계획 중이며 아직 구현되지 않았습니다. `recipe.md`의 라우팅 구조는 이미 `(on-prem, kubespray, none)` 조합을 지원하도록 설계되어 있어, Sub-Skill만 추가하면 됩니다.

---

## Data Plane 업그레이드

### Q: Self-managed Node Group도 업그레이드해주나요?

아닙니다. 현재는 Managed Node Group만 지원합니다. Managed Node Group은 IaC(Terraform)에서 버전을 변경하면 클라우드 프로바이더가 자동으로 Rolling Update를 수행합니다. 스킬은 이 과정을 모니터링하고 Gate 조건을 확인합니다.

Self-managed Node Group은 사용자가 직접 AMI 교체, drain, 노드 교체를 수행해야 합니다.

### Q: Karpenter로 관리하는 노드는 어떻게 업그레이드되나요?

Karpenter 노드는 IaC에서 AMI alias를 업데이트하면 Karpenter의 Drift Detection이 자동으로 노드를 교체합니다. 스킬은 Phase 5에서 이 과정을 모니터링하고, 모든 Karpenter 노드가 새 버전으로 교체될 때까지 대기합니다.

### Q: Fargate 프로파일은요?

지원하지 않습니다. Fargate Pod는 프로비저닝 시점에 최신 런타임이 적용되므로 별도의 노드 업그레이드 절차는 불필요하나, Skill 차원에서의 Pod 재시작 여부 검증은 포함되지 않습니다

---

## 롤백 및 실패 처리

### Q: 업그레이드 중 실패하면 자동으로 롤백하나요?

아닙니다. Kubernetes Control Plane 업그레이드는 되돌릴 수 없고, Data Plane도 이미 교체된 노드를 원복하는 것은 
복잡합니다. 스킬은 실패 시 즉시 중단하고 상세한 오류 내용을 보고합니다. 사용자가 상황을 판단한 후 다음 조치를 결정합니다.
모든 플랫폼이 롤백이 안되는 것은 아니지만 이것은 현재 버전에서는 불가능합니다.

### Q: terraform plan에서 예상치 못한 리소스 삭제가 나오면?

즉시 중단합니다. 스킬은 `terraform plan` 결과에서 `-/+` (destroy-recreate) 패턴을 감지하면 apply를 진행하지 않고 사용자에게 보고합니다. `time_sleep` 같은 무해한 리소스는 예외로 허용합니다.
현재는 Data Plane 등 실제 워크로드의 다운타임이 발생 할 수 있는 리소스를 감지하도록 선언되어 있습니다

### Q: Phase 6 Gate에서 "변경 없음"이라고 나오는데 실제로는 변경이 있었습니다

`terraform show -json`의 `resource_changes`에는 실제 변경이 없는 `no-op`와 `read` 항목도 포함됩니다. Phase 6 Gate(`phase_gate.py`)는 이 항목들을 자동으로 제외하고 실제 변경(create/update/delete/replace)만 카운트합니다. 따라서 no-op/read만 남은 경우 "변경 없음"으로 정상 보고됩니다.

---

## 설치 및 도구

### Q: install.sh가 기존 AI 도구 설정을 건드리나요?

아닙니다. `install.sh`는 각 도구의 전역 스킬 경로(예: `~/.claude/skills/`)에 `k8s-upgrade-skills/` 디렉토리를 복사하는 것이 전부입니다. MCP 설정, 도구 설정 파일 등은 일절 수정하지 않습니다.

### Q: 여러 AI 도구에 동시에 설치해도 되나요?

네. 각 도구의 스킬 경로가 다르기 때문에 충돌 없이 동시 설치 가능합니다. `./install.sh --all`로 한 번에 설치할 수 있습니다.


---

## API Deprecation

### Q: 업그레이드 대상 버전에서 사용 중인 API가 제거(Removed)되면 어떻게 되나요?

Phase 0 사전 검증의 COM-002(버전 호환성) 규칙에서 EKS Insights의 `UPGRADE_READINESS` 카테고리를 조회하여 Deprecated/Removed API 사용 여부를 확인합니다. 감지된 경우 해당 리소스와 API 버전을 보고하고, CRITICAL로 판정하여 업그레이드를 차단합니다.

다만 현재는 EKS Insights 또는 `kubectl` 기반 조회에 의존하며, 클러스터에 배포되지 않은 Helm chart나 CI/CD 파이프라인 내 매니페스트의 Deprecated API까지는 감지하지 못합니다. 배포 전 코드 레벨에서의 API 호환성 검사는 `pluto`, `kubent` 같은 별도 도구를 병행하는 것을 권장합니다.
