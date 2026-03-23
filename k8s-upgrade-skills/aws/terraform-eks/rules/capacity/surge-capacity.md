---
id: CAP-003
name: Rolling Update Surge 용량 검증
severity: HIGH
category: capacity
phase: pre-flight
applies_when: MNG rolling update 시
---

# CAP-003: Rolling Update Surge 용량 검증

## 목적

EKS MNG rolling update는 새 노드를 먼저 추가(surge)한 후 기존 노드를 drain한다. surge 노드를 위한 서브넷 IP, EC2 인스턴스 한도, EBS 볼륨 한도가 충분한지 확인한다.

## 검증 항목

### 1. MNG Update Config 확인

```bash
# MNG의 maxUnavailable / maxSurge 설정 확인
aws eks describe-nodegroup \
  --cluster-name ${CLUSTER_NAME} \
  --nodegroup-name <NODEGROUP_NAME> \
  --query 'nodegroup.{updateConfig:updateConfig, scalingConfig:scalingConfig, instanceTypes:instanceTypes, subnets:subnets}' \
  --output json
```

### 2. 서브넷 가용 IP 확인

```bash
# MNG가 사용하는 서브넷의 가용 IP 수
aws ec2 describe-subnets \
  --subnet-ids <SUBNET_IDS> \
  --query 'Subnets[].{SubnetId:SubnetId, AZ:AvailabilityZone, AvailableIPs:AvailableIpAddressCount, CidrBlock:CidrBlock}' \
  --output table
```

### 3. EC2 서비스 한도 확인

```bash
# On-Demand 인스턴스 한도 (vCPU 기준)
aws service-quotas get-service-quota \
  --service-code ec2 \
  --quota-code L-1216C47A \
  --query 'Quota.{Name:QuotaName, Value:Value}' \
  --output json

# 현재 실행 중인 인스턴스 수
aws ec2 describe-instances \
  --filters "Name=instance-state-name,Values=running" \
  --query 'Reservations[].Instances[].{Type:InstanceType, AZ:Placement.AvailabilityZone}' \
  --output table | tail -5
```

## Gate 조건

| 결과 | 판정 | 처리 |
|------|------|------|
| 서브넷 가용 IP > surge 노드 수 × 30 (Pod IP 포함) | ✅ PASS | 진행 |
| 서브넷 가용 IP < 50 | ⚠️ WARN | 보고 — IP 고갈 위험. 서브넷 확장 또는 prefix delegation 권장 |
| EC2 한도 근접 (현재 사용량 > 80%) | ⚠️ WARN | 보고 — 한도 증가 요청 권장 |
| 서브넷 가용 IP < 10 | ❌ FAIL | STOP — surge 노드 생성 불가 |

## 조치 방안

```bash
# 서브넷 IP 부족 시
# 옵션 1: VPC CNI prefix delegation 활성화
# 옵션 2: 서브넷 CIDR 확장

# EC2 한도 부족 시
aws service-quotas request-service-quota-increase \
  --service-code ec2 \
  --quota-code L-1216C47A \
  --desired-value <NEW_LIMIT>
```
