---
id: CAP-001
name: 노드 용량 여유분 검증
severity: HIGH
category: capacity
phase: pre-flight
applies_when: 항상
---

# CAP-001: 노드 용량 여유분 검증

## 목적

Rolling update 중 노드 1개가 drain되면 해당 노드의 Pod들이 나머지 노드로 이동해야 한다. 나머지 노드에 충분한 CPU/메모리 여유가 없으면 Pod가 Pending 상태에 빠진다. Karpenter가 있으면 자동 스케일아웃하지만, MNG(관리형 노드 그룹)는 고정 크기이므로 사전 확인이 필수다.

## 검증 명령어

```bash
# 노드별 할당 가능 리소스 vs 실제 사용량
kubectl get nodes -o json | python3 -c "
import json, sys
data = json.load(sys.stdin)
nodes = []
for node in data['items']:
    name = node['metadata']['name']
    alloc = node.get('status', {}).get('allocatable', {})
    
    # CPU: 밀리코어로 변환
    cpu_str = alloc.get('cpu', '0')
    if cpu_str.endswith('m'):
        cpu_alloc = int(cpu_str[:-1])
    else:
        cpu_alloc = int(cpu_str) * 1000
    
    # Memory: Mi로 변환
    mem_str = alloc.get('memory', '0')
    if mem_str.endswith('Ki'):
        mem_alloc = int(mem_str[:-2]) // 1024
    elif mem_str.endswith('Mi'):
        mem_alloc = int(mem_str[:-2])
    elif mem_str.endswith('Gi'):
        mem_alloc = int(mem_str[:-2]) * 1024
    else:
        mem_alloc = int(mem_str) // (1024*1024)
    
    # 라벨 정보
    labels = node['metadata'].get('labels', {})
    nodegroup = labels.get('nodegroup', labels.get('eks.amazonaws.com/nodegroup', 'karpenter'))
    
    nodes.append({
        'name': name.split('.')[0],  # 짧은 이름
        'cpu_alloc': cpu_alloc,
        'mem_alloc': mem_alloc,
        'nodegroup': nodegroup
    })

for n in nodes:
    print(f\"{n['name']}: CPU={n['cpu_alloc']}m MEM={n['mem_alloc']}Mi group={n['nodegroup']}\")
"

# Pod별 리소스 요청량 합산 (노드별)
kubectl get pods --all-namespaces -o json | python3 -c "
import json, sys
from collections import defaultdict
data = json.load(sys.stdin)
node_usage = defaultdict(lambda: {'cpu': 0, 'mem': 0, 'pods': 0})

for pod in data['items']:
    phase = pod.get('status', {}).get('phase', '')
    if phase not in ('Running', 'Pending'):
        continue
    node = pod.get('spec', {}).get('nodeName', 'unscheduled')
    if not node or node == 'unscheduled':
        continue
    
    for container in pod.get('spec', {}).get('containers', []):
        req = container.get('resources', {}).get('requests', {})
        
        cpu_str = req.get('cpu', '0')
        if cpu_str.endswith('m'):
            cpu = int(cpu_str[:-1])
        elif cpu_str:
            try:
                cpu = int(float(cpu_str) * 1000)
            except:
                cpu = 0
        else:
            cpu = 0
        
        mem_str = req.get('memory', '0')
        if mem_str.endswith('Mi'):
            mem = int(mem_str[:-2])
        elif mem_str.endswith('Gi'):
            mem = int(float(mem_str[:-2]) * 1024)
        elif mem_str.endswith('Ki'):
            mem = int(mem_str[:-2]) // 1024
        elif mem_str.endswith('M'):
            mem = int(mem_str[:-1])
        else:
            try:
                mem = int(mem_str) // (1024*1024)
            except:
                mem = 0
        
        node_usage[node.split('.')[0]]['cpu'] += cpu
        node_usage[node.split('.')[0]]['mem'] += mem
    node_usage[node.split('.')[0]]['pods'] += 1

print('노드별 리소스 요청량:')
for node, usage in sorted(node_usage.items()):
    print(f\"  {node}: CPU={usage['cpu']}m MEM={usage['mem']}Mi Pods={usage['pods']}\")
"
```

## Gate 조건

| 결과 | 판정 | 처리 |
|------|------|------|
| 노드 1개 drain 시 나머지 노드에 여유 충분 (CPU/MEM 사용률 < 80%) | ✅ PASS | 진행 |
| 여유 부족하지만 Karpenter 활성 | ✅ PASS | INFO — Karpenter가 자동 스케일아웃 |
| MNG 고정 크기 + 여유 부족 | ⚠️ WARN | 보고 — Pod Pending 가능성. 사용자에게 MNG 스케일업 권장 |
| 전체 노드 CPU/MEM 사용률 > 90% | ❌ FAIL | STOP — 스케일업 후 재시도 |

## 조치 방안

```bash
# MNG 스케일업 (Terraform)
# terraform.tfvars에서 desired_size 증가 후 apply

# 또는 kubectl로 임시 스케일업 (Terraform 외부 변경 주의)
aws eks update-nodegroup-config \
  --cluster-name ${CLUSTER_NAME} \
  --nodegroup-name <NODEGROUP_NAME> \
  --scaling-config desiredSize=<CURRENT+1>
```
