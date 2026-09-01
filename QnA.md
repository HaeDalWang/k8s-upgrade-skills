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
이는 사용자별 워크로드 배포 전략과 환경의 파편화가 심해 자동 수정 로직 구현에 제약이 있습니다. 추후 helm repo·yaml 파싱을 담당하는 별도 스크립트로 해결할 여지가 있으나 현재 버전으로는 아직입니다.

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

Fargate 프로파일 정의(IaC) 자체는 변경하지 않습니다. 다만 Control Plane 업그레이드 후 Fargate 노드는 **Pod가 재시작되어야 kubelet 버전이 갱신**되므로, Phase 7-0에서 잔류한 구버전 Fargate 노드를 감지하고 해당 Deployment(`coredns`, `karpenter` 등)를 `rollout restart`하여 새 버전 노드로 재스케줄합니다.

이는 실제 프로덕션 업그레이드에서 Fargate 노드 잔류가 Phase 7 최종 검증 FAIL을 유발했던 사례를 반영해 정식 절차로 포함한 것입니다. (`coredns` + `karpenter`를 선제 재시작하면 Phase 7을 1회에 통과합니다.)

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

Phase 0 사전 검증의 COM-004 규칙에서 EKS Insights의 `UPGRADE_READINESS` 카테고리를 조회하여 Deprecated/Removed API 사용 여부를 확인합니다. `ERROR`(제거된 API 등 차단 요인)는 CRITICAL로 판정하여 업그레이드를 차단하고, `WARNING`/`UNKNOWN`(deprecated 또는 미확정)은 HIGH로 판정하여 사용자 확인을 요구합니다. Insights 조회 자체가 실패하면(권한 등) 조용히 통과시키지 않고 HIGH로 보고합니다.

다만 EKS Insights는 **라이브 API 서버에 실제로 호출된 API만** 감지합니다. 클러스터에 아직 배포되지 않은 Helm chart나 CI/CD 파이프라인 내 매니페스트의 Deprecated API까지는 보지 못합니다. 배포 전 코드 레벨에서의 API 호환성 검사는 `pluto`, `kubent` 같은 별도 도구를 병행하는 것을 권장합니다.

---

## Helm 차트 호환성

### Q: 설치된 Helm 차트가 대상 K8s 버전을 지원하는지 미리 알 수 있나요?

`helm-k8s-compat` 스킬(install.sh로 함께 설치됨)이 이 역할을 합니다. `helm ls`로 설치된 Release를 수집한 뒤, De-facto 표준 차트 31종을 큐레이션한 registry와 대조하여 호환성 문제를 검출합니다. "Helm 차트 호환성 점검해줘"로 단독 실행하거나, 업그레이드 Phase 0 보조로 사용할 수 있습니다.

현재/대상 버전을 같게 주면(`--current 1.35 --target 1.35`) 업그레이드 없이 **지금 상태만 점검**합니다. 차트는 클러스터가 가만히 있어도 EOL을 맞고 지원 매트릭스는 새 K8s가 나오면서 바뀌므로, 주기적으로 돌려 현재 버전 기준으로 이미 지원 범위를 벗어난 차트를 찾는 용도입니다.

검출하는 항목:

- **지원 버전 윈도우 초과** — 예: ingress-nginx 4.13.x는 K8s 1.33이 상한입니다. 1.34로 올리려면 차트를 4.14.x 이상으로 먼저 올려야 하는데, `kubeVersion` 필드(`>=1.21`)만 보면 이 문제를 놓칩니다.
- **retirement / EOL** — ingress-nginx는 2026-03 retirement되어 보안 패치가 없습니다. cert-manager는 release당 ~4개월 지원이라 EOL 날짜가 지난 버전을 쓰고 있을 수 있습니다.
- **minor 강결합** — cluster-autoscaler는 app minor가 K8s minor와 1:1로 일치해야 합니다.
- **수동 업그레이드 함정** — Helm v3는 CRD를 자동 업데이트하지 않습니다. aws-load-balancer-controller·kube-prometheus-stack처럼 CRD를 가진 차트는 `kubectl apply`로 CRD를 수동 갱신해야 하며, 버전 점프에 따라 IAM 정책·webhook 전환이 필요할 수 있습니다.

판정은 `helm_compat_check.py`의 exit code로 결정됩니다(0=문제없음, 1=차단, 2=확인 필요, 64=입력 오류, 127=helm 미존재). 기존 gate_check.py와 동일하게 LLM이 우회할 수 없습니다. `64`는 게이트 판정이 아니라 잘못된 호출이므로 WARN으로 읽어서는 안 됩니다.

### Q: 모든 Helm 차트를 검사하나요?

아닙니다. registry는 EKS 환경에서 사실상 표준으로 쓰이는 차트를 **깊게** 큐레이션한 것으로, 모든 차트를 망라하지 않습니다. registry에 없는 차트는 자동 평가 대상이 아니며 **"수동 검토 필요"(INFO)로 보고**해 게이트를 차단하지 않되 조용히 통과시키지도 않습니다(false 안심 방지). 해당 차트는 `helm show chart <release>`와 릴리스 노트로 직접 확인해야 합니다.

`kubeVersion` 필드를 자동 판정에 쓰지 않는 이유도 여기 있습니다. 대부분의 차트가 하한만 선언(`>=1.21`)하기 때문에 마이너 업그레이드 차단 요인을 잡지 못하고, 그걸 근거로 통과시키면 근거 없는 안심만 주게 됩니다.

이는 의도적인 선택입니다. 실전 차트는 호환성 정보가 부실하거나 모델이 제각각이라(어떤 건 윈도우, 어떤 건 minor 강결합, 어떤 건 매트릭스 자체가 없음), 표준 차트를 정확히 다루는 것이 얕고 넓은 자동 추측보다 신뢰할 수 있습니다. 새 차트는 `registry/_schema.md`의 체크리스트를 따라 추가할 수 있습니다.

### Q: EKS Insights·kubent와 무엇이 다른가요?

상호 보완 관계입니다. EKS Insights와 kubent는 **라이브 API 서버에 실제로 호출된 API**를 스캔합니다(제거/Deprecated API 객체 감지). 반면 `helm-k8s-compat`는 **차트 자체의 호환성**을 봅니다 — 차트 버전이 대상 K8s를 지원하는지, 컨트롤러가 retirement되지 않았는지, 차트를 올릴 때 어떤 수동 단계가 필요한지. 이는 API 스캔으로는 나오지 않고 릴리스 노트·지원 매트릭스에만 있는 지식입니다. 두 부류를 함께 쓰는 것을 권장합니다.
