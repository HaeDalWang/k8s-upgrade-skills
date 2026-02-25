# ArgoCD Helm 차트 (업그레이드·트러블슈팅 테스트)

ArgoCD가 이 디렉터리(또는 이 레포의 `charts/` 경로)를 Helm 소스로 바라보고, values 파일만 바꿔서 여러 시나리오를 배포할 수 있도록 구성했다.

## 차트: upgrade-test-app

| 파일 | 용도 |
|------|------|
| `values.yaml` | 기본 배포 (PDB/PV 없음) |
| `values_pdb.yaml` | PDB 활성화 — drain/업그레이드 시 `disruptionsAllowed` 트러블슈팅 |
| `values_pv.yaml` | StatefulSet + PVC — 노드 롤링 시 볼륨·재스케줄 트러블슈팅 |

## ArgoCD Application 예시

- **기본**: `values.yaml`  
  `source.helm.valueFiles`: `["values.yaml"]`

- **PDB 시나리오**: `values_pdb.yaml`  
  `source.helm.valueFiles`: `["values.yaml", "values_pdb.yaml"]`

- **PV 시나리오**: `values_pv.yaml`  
  `source.helm.valueFiles`: `["values.yaml", "values_pv.yaml"]`

앱 이미지·리소스 등은 추후 변수 파일에 추가하면 된다.
