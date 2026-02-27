# **EKS 및 Karpenter 환경에서의 Bitnami ETCD 무중단 업그레이드 및 리더 선출 최적화 심층 연구**

## **서론: 동적 노드 환경에서의 분산 스토리지 운영과 다운타임의 상관관계**

클라우드 네이티브 아키텍처가 성숙해짐에 따라, Kubernetes는 단순한 컨테이너 오케스트레이션 도구를 넘어 인프라스트럭처의 핵심 제어 평면(Control Plane)으로 자리 잡았다. 이러한 환경에서 분산 키-값(Key-Value) 저장소인 etcd는 Kubernetes 클러스터 자체의 상태 데이터를 저장할 뿐만 아니라, 높은 가용성과 엄격한 데이터 일관성을 요구하는 다양한 분산 애플리케이션(예: 분산 락, API 게이트웨이 라우팅 테이블, 클러스터 캐시 등)의 백엔드 저장소로 널리 채택되고 있다. 특히, Helm 패키지 매니저를 통해 배포를 자동화하는 Bitnami etcd 차트는 운영의 편의성과 검증된 보안 구성을 제공하여 프로덕션 환경에서 표준적인 배포 방식으로 자리매김하였다.  
그러나 Amazon EKS(Elastic Kubernetes Service)와 Karpenter를 결합한 고도로 동적인 노드 프로비저닝 환경에서는 etcd와 같은 Stateful 워크로드를 운영할 때 새로운 차원의 도전 과제가 발생한다. Karpenter는 리소스 활용률을 극대화하기 위해 빈 노드를 회수(Scale-in)하거나, 파드들을 더 저렴하고 효율적인 노드로 통합(Consolidation)하며, 스팟 인스턴스(Spot Instance)의 회수 시그널에 반응하여 밀리초 단위로 노드를 교체한다. 또한, 최신 AMI(Amazon Machine Image) 적용이나 보안 패치를 위한 구성 편차(Drift) 해소 과정에서도 노드의 자발적 중단(Voluntary Disruption)이 빈번하게 발생한다.  
이러한 동적 환경에서 3개의 복제본(Replica)과 minAvailable: 2로 설정된 PodDisruptionBudget(PDB)을 갖춘 etcd 클러스터를 운영할 때, 파드의 강제 종료와 재시작은 일상적인 이벤트가 된다. 문제는 etcd가 단일 리더(Leader) 기반의 Raft 합의 알고리즘(Consensus Algorithm)으로 동작한다는 점이다. 노드 교체나 Helm 차트 버전 업그레이드를 위한 롤링 업데이트(Rolling Update) 중 현재 리더 역할을 수행 중인 etcd 파드가 삭제될 경우, 클러스터는 새로운 리더를 선출하기 위한 선거(Election) 상태에 돌입하게 되며, 이 기간 동안 모든 쓰기(Write) 연산이 차단되어 클라이언트는 타임아웃이나 502 Bad Gateway 에러와 같은 명백한 다운타임을 겪게 된다.  
본 연구의 목적은 Bitnami etcd Helm 차트를 활용하는 EKS 및 Karpenter 환경에서 리더 파드 삭제 시 발생하는 다운타임을 완전히 제거(Zero-Downtime)할 수 있는 아키텍처적 접근법과 구체적인 파훼법을 규명하는 것이다. 특히, 인간의 개입(Human Resource)을 완전히 배제하고, Kubernetes의 네이티브 라이프사이클 훅(Lifecycle Hook)인 PreStop 쉘 스크립트와 Karpenter의 종료 유예 정책을 조합하여 자연스럽고 우아한 리더십 이양(Move-Leader) 메커니즘을 구현하는 방안을 심도 있게 분석한다.

## **etcd의 분산 아키텍처와 Raft 합의 알고리즘의 한계**

다운타임 없는 자연스러운 방안을 도출하기 위해서는 먼저 etcd 클러스터의 내부 동작 원리와 리더 선출 과정에서 발생하는 지연의 근본 원인을 이해해야 한다. etcd는 분산 시스템의 데이터 일관성을 보장하기 위해 Raft 알고리즘을 사용한다. Raft 알고리즘에서 클러스터의 모든 멤버는 리더(Leader), 팔로워(Follower), 후보(Candidate) 중 하나의 상태를 가진다. 클라이언트의 모든 데이터 변경(Put, Delete 등) 요청은 리더에게 전달되며, 리더는 이를 자신의 로그에 기록한 후 팔로워들에게 복제(Replication)한다. 과반수(Quorum)의 팔로워가 로그를 성공적으로 수신했음을 확인하면 리더는 해당 변경 사항을 커밋(Commit)하고 클라이언트에게 성공 응답을 반환한다.  
3개의 복제본으로 구성된 etcd 클러스터에서 Quorum은 2이다. 즉, 1개의 노드가 장애를 일으키거나 유지보수를 위해 종료되더라도 나머지 2개의 노드가 정상 작동한다면 클러스터는 데이터의 읽기 및 쓰기 가용성을 유지할 수 있어야 한다. 그러나 이는 '최종적인 가용성'을 의미할 뿐, '무중단'을 보장하는 것은 아니다.  
리더 노드가 예기치 않게(또는 정상적인 SIGTERM을 받고) 종료될 경우 발생하는 시퀀스는 다음과 같다. 리더는 주기적으로 팔로워들에게 자신이 건재함을 알리는 하트비트(Heartbeat) 메시지를 전송한다. 리더 프로세스가 종료되면 하트비트 전송이 중단된다. 팔로워들은 사전에 설정된 election-timeout 시간 동안 하트비트를 수신하지 못하면 기존 리더가 사망한 것으로 간주하고 스스로를 후보(Candidate)로 격상시켜 새로운 리더 선거를 시작한다. 이 선거 과정이 완료되고 새로운 리더가 모든 팔로워와 상태를 동기화하기 전까지, etcd 클러스터는 어떠한 쓰기 요청도 처리할 수 없는 블로킹(Blocking) 상태에 빠진다.  
즉, election-timeout에 의존하는 수동적인(Passive) 리더 선출 방식 자체가 필연적으로 수 초 이상의 다운타임을 유발하는 구조적 결함을 내포하고 있는 것이다.

| 타임아웃 파라미터 | 기본값 | 기능적 역할 및 다운타임과의 관계 |
| :---- | :---- | :---- |
| heartbeat-interval | 100ms | 리더가 팔로워에게 생존을 알리는 주기. 짧을수록 빠르게 장애를 인지하지만 네트워크 부하가 증가함. |
| el\[span\_22\](start\_span)\[span\_22\](end\_span)\[span\_25\](start\_span)\[span\_25\](end\_span)ection-timeout | 1000ms | 팔로워가 리더의 부재를 인지하고 선거를 시작하기까지 대기하는 시간. 리더 파드 삭제 시 클라이언트는 최소 이 시간 이상의 다운타임을 겪게 됨. |

따라서 롤링 업데이트나 노드 축출(Eviction) 시 다운타임을 없애기 위한 핵심 명제는 "팔로워들이 리더의 부재를 인지하고 선거를 시작하도록 방치하는 것"이 아니라, "현재 리더가 종료되기 직전에 능동적(Proactive)으로 다른 건강한 팔로워에게 리더십을 즉시 이양하는 것"이다. 이를 가능하게 하는 명령어가 바로 etcdctl move-leader이다.

## **Bitnami etcd Helm 차트의 기본 설계 철학과 구조적 맹점**

능동적인 리더십 이양 메커니즘을 구현하기에 앞서, 현재 프로덕션 환경에서 널리 사용되는 Bitnami etcd Helm 차트의 기본 동작 방식을 분석하고 이를 파훼해야 한다. Bitnami 차트는 설치와 구성의 편의성을 제공하지만, 동적인 Kubernetes 환경에서의 무중단 운영 측면에서는 매우 치명적인 기본 설정값(Default Values)을 가지고 있다.  
가장 문제가 되는 설정은 removeMemberOnContainerTermination: true이다. 이 변수가 활성화되어 있으면, 파드가 종료될 때 컨테이너 내부의 /opt/bitnami\[span\_1\](start\_span)\[span\_1\](end\_span)/scripts/etcd/prestop.sh 스크립트가 실행된다. 이 스크립트의 주된 논리는 파드가 죽기 전에 클러스터 멤버십에서 해당 파드의 ID를 영구적으로 삭제(etcdctl member remove)하는 것이다.  
이러한 설계는 클러스터의 영구적인 스케일 다운(Scale-down, 예: Replica를 3에서 2로 줄이는 경우) 시에는 매우 유용하다. 존재하지 않는 파드가 멤버십에 계속 남아있으면 클러스터는 Quorum을 충족하지 못해 영구적인 장애 상태에 빠질 수 있기 때문이다. 그러나 노드의 교체, 파드의 재스케줄링, 혹은 Helm 릴리스의 롤링 업그레이드와 같이 파드가 일시적으로 종료되었다가 동일한 식별자와 데이터를 가지고 다시 시작되어야 하는 상황에서는 심각한 충돌을 야기한다.

### **멤버 삭제(Member Remove) 로직이 야기하는 장애 시퀀스 분석**

파드가 롤링 업그레이드나 Karpenter에 의해 재시작될 때 removeMemberOnContainerTermination 로직이 개입하면 다음과 같은 연쇄적인 장애가 발생한다.

1. **멤버십 영구 탈퇴**: 파드(예: etcd-0)가 SIGTERM을 받으면 prestop.sh가 실행되어 클러스터에서 etcd-0의 멤버 ID를 삭제한다.  
2. **파드 재시작 및 데이터 불일치**: Kube-scheduler에 의해 파드가 새로운 노드에 다시 배포된다. 이 파드는 StatefulSet의 특성상 이전에 사용하던 Persistent Volume(PV)을 그대로 마운트한다.  
3. **합류 거부(Join Rejection)**: 시작 프로세스(libetcd.sh) 중에 etcd 바이너리는 마운트된 데이터 디렉터리(/bitnami/etcd/data)에 남아있는 기존 멤버 상태를 읽어들여 클러스터에 다시 합류하려 시도한다. 그러나 기존 클러스터 멤버(예: etcd-1, etcd-2)들은 해당 멤버 ID가 이미 영구적으로 삭제(Removed)된 것으로 인지하고 있으므로 합류를 거부한다.  
4. **CrashLoopBackOff 상태 진입**: 파드는 the member has been permanently removed from the cluster 또는 etcdserver: re-configuration failed due to not enough started members와 같은 치명적인 에러를 로그에 남기고 강제 종료되며, 지속적인 재시작 루프(CrashLoopBackOff)에 빠지게 된다.

결과적으로 이 기본 설정을 그대로 둔 채 노드를 교체하게 되면, 클러스터는 자가 치유(Self-healing) 기능을 상실하게 되며, 결국 관리자(Human Resource)가 개입하여 고립된 PVC를 수동으로 삭제하거나, 임시 컨테이너를 띄워 etcdctl member add 명령을 통해 클러스터를 복구해야 하는 심각한 운영 오버헤드를 초래한다.  
더욱이 prestop.sh 스크립트 내부에서 /bitnami/etcd/data/member\_id 파일을 참조하는 로직이 꼬이면서 Error: bad member ID arg (strconv.ParseUint: parsing "": invalid syntax), expecting ID in Hex와 같은 예기치 않은 오류가 발생하기도 한다.

### **파훼법: 기본 PreStop 훅의 비활성화**

다운타임을 없애고 자연스러운 업그레이드를 가능하게 하는 첫 번째 단계는 바로 이 공격적인 멤버 강제 탈퇴 스크립트를 비활성화하는 것이다. Bitnami Helm 차트의 values.yaml에서 다음과 같이 설정하여 이 기능을 꺼야 한다.  
`removeMemberOnContainerTermination: false`

이 설정을 적용하면 파드가 종료되더라도 클러스터 멤버십은 유지된다. 재시작된 파드는 동일한 볼륨의 데이터를 기반으로 클러스터에 팔로워(Follower) 자격으로 자연스럽게 재합류하게 되며, 데이터 동기화(Raft Log Catch-up) 절차를 거쳐 정상 상태로 복구된다. 인간의 개입이 포함된 수동 복구 작업이 완전히 배제되는 것이다.

## **무중단 리더 이양(Move-Leader) 메커니즘의 선제적 적용**

기본 맹점을 제거하여 파드의 안전한 재시작 환경을 구축했다면, 다음 단계는 리더 파드가 삭제될 때 발생하는 선거 타임아웃(Election Timeout) 블로킹을 해소하는 것이다. 서론에서 언급했듯, 이 문제를 해결하는 가장 우아한 방법은 파드가 종료되기 직전에 스스로 리더십을 검증하고, 본인이 리더라면 다른 건강한 팔로워에게 권한을 즉시 넘겨주는 것이다.  
etcdctl move-leader 명령어는 이러한 목적을 위해 설계되었다. 이 명령은 클러스터의 합의를 거쳐 리더십을 즉각적으로 이전하며, 타임아웃 대기 없이 즉시 쓰기 권한이 양도되므로 클라이언트가 경험하는 다운타임은 사실상 제로(Zero)에 수렴하게 된다.

| 상태 전이 방식 | 메커니즘 | 소요 시간 및 서비스 영향 (다운타임) |
| :---- | :---- | :---- |
| **수동적 선거 (Passive Election)** | 리더 강제 종료 \\rightarrow 타임아웃 대기 \\rightarrow 후보 격상 \\rightarrow 투표 및 선출 | 타임아웃 시간(기본 1\~5초) 동안 모든 쓰기 연산 실패. |
| **능동적 이양 (Proactive Move-Leader)** | 종료 전 리더십 이양 명령 실행 \\rightarrow 타겟 노드로 즉각 권한 이전 \\rightarrow 기존 노드 종료 | 이양 즉시 완료(밀리초 단위). 트래픽 드레인 시간만 보장되면 다운타임 없음. |

### **Kubernetes PreStop 훅을 활용한 라이프사이클 제어**

Kubernetes는 파드를 종료할 때 내부 프로세스에 SIGTERM 시그널을 보내기 직전, 컨테이너 내에서 특정 명령어 나 스크립트를 실행할 수 있는 PreStop 라이프사이클 훅을 제공한다. removeMemberOnContainerTermination: false로 비활성화된 기존의 prestop.sh 대신, 커스텀 PreStop 쉘 스크립트를 작성하여 values.yaml의 lifecycleHooks 섹션에 주입해야 한다.

#### **무중단 리더 이양 쉘 스크립트의 논리적 구성 및 심층 분석**

효과적인 move-leader 스크립트는 단순히 명령어를 실행하는 것을 넘어, 현재 상태를 정확히 진단하고 안전하게 커넥션을 드레인(Draining)하는 과정을 포함해야 한다. 다음은 이를 구현하기 위해 쉘 환경에서 구성되어야 하는 논리적 흐름이다.

1. **상태 진단 및 리더 확인**: 현재 종료를 앞둔 컨테이너가 리더 역할을 수행 중인지 확인해야 한다. etcdctl endpoint status 명령을 사용하면 클러스터 내 모든 엔드포인트의 리더 여부(IS LEADER)를 테이블이나 CSV 형식으로 반환받을 수 있다.  
2. **타겟 노드 선정**: 본인이 리더라면, 리더십을 넘겨받을 건강한 팔로워를 찾아야 한다. 동일한 endpoint status 명령 결과에서 본인의 호스트네임을 제외(grep \-v)한 나머지 노드 중 하나의 멤버 ID를 파싱하여 추출한다.  
3. **리더십 이전**: 추출된 타겟 멤버 ID를 인자로 하여 etcdctl move-leader \<NEW\_LEADER\_ID\> 명령을 실행한다.  
4. **연결 드레인 대기 (Connection Draining)**: 가장 중요한 단계 중 하나이다. 리더십이 넘어간 즉시 컨테이너가 종료(SIGTERM)되면, Kubernetes 내부의 Service Endpoint (IPVS/iptables) 규칙이나 클라이언트 측 로드 밸런서가 새로운 라우팅 상태를 미처 갱신하지 못해 일시적인 라우팅 실패(502 에러 등)가 발생할 수 있다. 이를 방지하기 위해 sleep 15와 같은 지연 시간을 두어, 기존에 연결된 트랜잭션들이 안전하게 완료되고 신규 연결이 새로운 리더로 맺어질 수 있는 물리적 시간을 확보해야 한다.

#### **Bitnami 컨테이너 환경을 고려한 스크립트 구현**

Bitnami etcd 이미지는 보안 및 호환성을 위해 etcdctl 실행 시 명시적인 인증서 체인이나 환경 변수 설정(ETCDCTL\_API=3, etcdctl\_auth\_flags 등)을 요구하는 경우가 많다. 따라서 스크립트 작성 시 Bitnami가 기본 제공하는 스크립트 라이브러리(/opt/bitnami/scripts/libetcd.sh 또는 /etc/profile.d/etcd-all)를 소싱(source)하여 환경 변수를 상속받는 것이 안정적이다. 또한, 출력 결과를 awk나 cut 명령어로 파싱할 때 etcdctl의 출력 포맷을 simple 대신 스크립트 처리에 용이한 형식으로 강제하는 것이 유리할 수 있다.  
`lifecycleHooks:`  
  `preStop:`  
    `exec:`  
      `command:`  
        `- /bin/bash`  
        `- -c`  
        `- |`  
          `[span_32](start_span)[span_32](end_span)set -o pipefail`  
          `# Bitnami 환경 변수 로드`  
          `source /opt/bitnami/scripts/libetcd.sh`   
            
          `echo "Starting custom PreStop hook for graceful leader transfer..."`  
            
          `# 현재 노드의 리더 여부 판별`  
          `# etcdctl endpoint status 명령어 결과에서 호스트네임을 매칭하여 IS_LEADER(5번째 컬럼) 값을 추출`  
          `AM_LEADER=$(etcdctl endpoint status | grep $(hostname) | cut -d ',' -f 5 | tr -d ' ')`  
            
          `if]; then`  
            `echo "This node $(hostname) is the leader. Initiating move-leader process."`  
              
            `# 리더가 아닌(grep -v) 활성 상태의 팔로워 노드 중 하나의 멤버 ID(2번째 컬럼)를 추출`  
            `NEW_LEADER=$(etcdctl endpoint status | grep -v $(hostname) | cut -d ',' -f 2 | tr -d ' ' | tail -n '-1')`  
              
            `if]; then`  
              `echo "Moving leadership to member: $NEW_LEADER"`  
              `etcdctl move-leader $NEW_LEADER`  
                
              `# 리더십 이양 후 네트워크 라우팅 전파 및 클라이언트 세션 안전 종료를 위한 대기 시간 부여`  
              `echo "Leadership moved. Waiting 15 seconds for connection draining..."`  
              `sleep 15`  
            `else`  
              `echo "Failed to find a valid follower to transfer leadership."`  
            `fi`  
          `else`  
            `echo "This node is a follower. Proceeding with graceful shutdown..."`  
            `# 팔로워 노드도 네트워크 갱신을 위해 최소한의 대기 시간을 가짐`  
            `sleep 5`  
          `fi`

이 커스텀 PreStop 훅을 통해 파드 종료 이벤트가 발생하면, etcd는 클라이언트에 대한 서비스를 중단하지 않고 즉각 쓰기 권한을 이양한다. 이후 15초의 지연 시간을 거쳐 Kubelet에 의해 우아하게 종료되며, removeMemberOnContainerTermination: false 설정 덕분에 재스케줄링 시에도 어떠한 데이터 충돌 없이 매끄럽게 클러스터로 복귀하게 된다.

## **Karpenter 환경에서의 노드 중단(Disruption) 및 라이프사이클 튜닝**

ETCD 레벨에서의 우아한 종료 스크립트(PreStop Hook)가 완벽하게 구성되었다 하더라도, EKS와 Karpenter가 주도하는 인프라 레벨의 라이프사이클 정책이 이 스크립트의 실행을 보장해주지 않으면 모든 논리는 무용지물이 된다.  
Karpenter는 비용 효율성과 리소스 최적화를 위해 매우 공격적으로 노드를 관리한다. 만료(Expiration), 통합(Consolidation), 편차(Drift) 등의 이유로 노드를 회수하기로 결정하면, 해당 노드에 떠 있는 파드들을 다른 노드로 축출(Eviction)하기 시작한다. 이때 무중단 서비스를 유지하기 위해 반드시 조율되어야 하는 세 가지 핵심 메커니즘이 존재한다.

### **1\. PodDisruptionBudget (PDB)의 방어 기제**

PDB는 클러스터 관리자가 자발적 중단(Voluntary Disruption) 상황에서 동시에 종료될 수 있는 파드의 최대 갯수를 제어할 수 있게 해주는 안전 장치이다. etcd의 복제본 수가 3개일 때 Quorum은 2이므로, 반드시 minAvailable: 2 (또는 maxUnavailable: 1)로 설정된 PDB가 존재해야 한다.  
Karpenter의 축출 컨트롤러는 PDB를 엄격히 준수한다. Karpenter가 동시에 여러 노드를 회수하려 하더라도, PDB에 의해 보호받고 있는 etcd 파드들은 한 번에 하나씩만 순차적으로 축출된다. 첫 번째 파드가 축출되어 다른 노드에서 성공적으로 Ready 상태가 된 이후에야 두 번째 파드에 대한 축출이 허용되므로, 클러스터의 Quorum 붕괴를 원천적으로 방지할 수 있다.

### **2\. Termination Grace Period의 계층적 조율 (중요)**

무중단 업그레이드와 관련하여 가장 간과하기 쉬운 설정이자 치명적인 장애를 유발하는 요소는 바로 유예 시간(Grace Period)의 상관관계이다. 유예 시간은 Kubernetes 파드 레벨과 Karpenter 노드풀(NodePool) 레벨 모두에 존재하며, 이 둘의 설정값이 조화롭지 않으면 PreStop 훅이 강제로 취소(SIGKILL)되는 불상사가 발생한다.

#### **Kubernetes 파드 레벨 (terminationGracePeriodSeconds)**

Kubelet은 파드 종료 시그널(SIGTERM)을 보낸 후 terminationGracePeriodSeconds에 정의된 시간만큼 대기한다. 이 시간 내에 PreStop 훅과 프로세스가 정상 종료되지 않으면 SIGKILL을 보내 강제로 컨테이너를 죽인다. 앞서 우리가 작성한 PreStop 훅에는 sleep 15가 포함되어 있으며, etcd 자체 프로세스의 안전한 정리를 고려할 때 기본값인 30초는 너무 촉박하다. 따라서 파드 레벨의 유예 시간을 최소 60초에서 90초 정도로 넉넉하게 연장해야 한다.  
`# 파드 설정`  
`terminationGracePeriodSeconds: 90`

#### **Karpenter 노드 레벨 (terminationGracePeriod)**

Karpenter v1 API의 NodePool(또는 구버전의 NodeClaim) 사양에는 노드 만료 시 파드가 드레인(Drain)되기를 기다려주는 최대 한계 시간인 terminationGracePeriod 속성이 존재한다. Karpenter는 노드 회수를 시작할 때 파드를 축출하려 시도하지만, PDB 제약이나 앞서 설정한 PreStop 훅의 지연 시간 때문에 파드가 즉시 종료되지 않고 버틸 수 있다. 만약 Karpenter의 유예 시간이 파드의 유예 시간보다 짧거나, PDB 대기 시간을 충분히 커버하지 못할 경우, Karpenter는 PDB와 PreStop 훅을 **무시하고(Bypassing)** 해당 노드를 클라우드 프로바이더(AWS) 레벨에서 강제로 파괴해 버린다. 이는 리더 이양 스크립트가 미처 완료되기도 전에 노드의 전원이 차단되는 것과 같으므로 끔찍한 다운타임을 초래한다.  
따라서 Karpenter NodePool의 terminationGracePeriod는 애플리케이션의 롤링 업데이트나 PDB 병목 현상을 충분히 기다려 줄 수 있도록 최소 10분(600s) 이상의 넉넉한 값으로 설정되어야 한다.

| 유예 시간 정책 | 적용 계층 | 권장 설정값 | 역할 및 설정 사유 |
| :---- | :---- | :---- | :---- |
| terminationGracePeriodSeconds | K8s Pod Spec | 60 \~ 120초 | etcdctl move-leader 명령 실행 및 15초 이상의 커넥션 드레인(sleep)을 완수할 수 있는 논리적 시간 확보. |
| terminationGracePeriod | Karpenter NodePool | 600s \~ 1200s | PDB로 인해 다른 etcd 노드의 복구를 기다리거나, 긴 PreStop 훅이 끝날 때까지 노드를 강제 삭제하지 않고 기다려주기 위함. |

### **3\. Spot Interruption (스팟 중단) 환경에 대한 고찰**

AWS 스팟 인스턴스를 활용하여 비용 최적화를 꾀하는 경우, AWS는 스팟 인스턴스 회수 2분(120초) 전에 중단 알림(Interruption Notice)을 발송한다. AWS Node Termination Handler 또는 Karpenter의 네이티브 Interruption 핸들러가 이를 감지하면 즉시 해당 노드를 Cordon하고 파드를 드레인하기 시작한다.  
이 경우에도 다운타임을 피할 수 있는지에 대한 의문이 생길 수 있다. 결론부터 말하자면, "가능하다." 2분이라는 물리적 시간은 우리가 설계한 move-leader PreStop 훅(최대 20\~30초 소요)이 실행되고 완료되기에 차고 넘치는 시간이다. 스팟 중단 시그널이 발생하더라도 Kubernetes의 정상적인 축출 프로세스(Eviction API)가 호출되므로 PreStop 훅은 정상적으로 트리거된다. 다만, 스팟 중단은 PDB를 무시하는 클라우드 프로바이더 레벨의 강제 회수이기 때문에, 동시에 2개 이상의 etcd 노드가 스팟 회수를 당할 확률을 낮추기 위해 topologySpreadConstraints와 함께 여러 가용 영역(AZ) 및 여러 인스턴스 타입으로 분산 배치(Diversification)하는 인프라 아키텍처 구성이 수반되어야 한다.

### **극단적 안전장치: do-not-disrupt 어노테이션**

리더 이양 스크립트와 PDB의 결합만으로도 자연스러운 자동화 방안이 완성되지만, etcd와 같은 최상위 중요도의 StatefulSet 워크로드에 대해 Karpenter의 자발적 중단(통합, 만료 등) 자체를 완전히 차단하고자 한다면 파드에 karpenter.sh/do-not-disrupt: "true" 어노테이션을 부여할 수 있다. 이 어노테이션이 존재하면 Karpenter는 어떠한 경우에도 해당 파드가 띄워져 있는 노드를 회수하려 시도하지 않는다. 그러나 이 방식을 사용하면 결국 노드 업그레이드나 패치 작업 시 관리자가 수동으로 어노테이션을 제거(Human Resource 개입)해야 하므로 "자연스러운 무중단 자동화"라는 원래의 취지와는 다소 멀어지게 된다. 따라서 PDB와 적절한 PreStop 훅을 신뢰하고 자동화된 교체 사이클을 수용하는 것이 진정한 클라우드 네이티브 운영 방식에 부합한다.

## **Multi-Availability Zone (다중 가용 영역) 환경의 네트워크 지연과 타임아웃 튜닝**

클라우드 환경에서 고가용성(High Availability)을 보장하기 위해서는 3개의 etcd 파드가 단일 인스턴스나 단일 가용 영역(AZ)에 몰리지 않고 균등하게 분산되어야 한다. 이를 위해 Helm 차트의 topologySpreadConstraints 및 podAntiAffinity 설정을 사용하여 노드 및 AZ 레벨의 분산을 강제(Hard Requirement)해야 한다.  
이처럼 물리적으로 분리된 다중 가용 영역(Multi-AZ) 환경에서는 각 AZ 간의 네트워크 지연 시간(Network Latency)이 발생한다. 앞서 언급한 바와 같이, etcd의 기본 heartbeat-interval은 100ms, election-timeout은 1000ms로, 이는 지연 시간이 거의 없는 동일 랙(Rack) 수준의 로컬 네트워크 환경에 최적화된 수치이다.  
AWS EKS와 같은 환경에서 AZ 간 패킷 왕복 시간(RTT)이 가변적이거나 클라우드 스토리지(EBS)의 디스크 I/O가 간헐적인 스파이크를 보일 경우, 이 공격적인 기본 타임아웃 설정은 치명적인 문제를 야기한다. 리더가 정상임에도 불구하고 네트워크 지터(Jitter)로 인해 팔로워가 하트비트를 제때 받지 못해 불필요한 선거(Spurious Election)를 유발하며, 이는 곧장 일시적인 클러스터 프리징(다운타임)으로 직결된다.  
이러한 현상을 방지하고, PreStop 훅에 의한 우아한 종료가 진행되는 동안 클러스터의 전반적인 안정성을 높이기 위해 타임아웃 파라미터를 인프라 환경에 맞게 튜닝(Tuning)해야 한다. 일반적인 지침은 다음과 같다.

1. **Heartbeat Interval (--heartbeat-interval)**: 클러스터 멤버 간 평균 왕복 시간(RTT)을 고려하여 설정한다. AWS Multi-AZ 환경에서는 네트워크 대역폭과 디스크 I/O 편차를 흡수하기 위해 기본값 100ms에서 200ms \~ 250ms 수준으로 상향 조정하는 것이 권장된다.  
2. **Election Timeout (--elect\[span\_151\](start\_span)\[span\_151\](end\_span)\[span\_153\](start\_span)\[span\_153\](end\_span)ion-timeout)**: 이 값은 하트비트 주기의 최소 5배에서 10배 사이로 설정해야 한다. 글로벌 클러스터나 부하가 심한 클라우드 환경에서는 2500ms에서 최대 5000ms 수준으로 상향 조정하여 불필요한 리더 변경을 최대한 억제해야 한다.

Bitnami Helm 차트에서는 extraEnvVars 배열을 통해 시작 프로세스에 환경 변수를 손쉽게 주입할 수 있다.  
`extraEnvVars:`  
  `- name: ETCD_HEARTBEAT_INTERVAL`  
    `value: "250"`  
  `- name: ETCD_ELECTION_TIMEOUT`  
    `value: "2500"`

이 튜닝은 move-leader를 활용한 계획된 종료(Planed Shutdown) 상황뿐만 아니라, 하드웨어 장애나 OOM Kill과 같이 Karpenter가 미처 대응하지 못하는 돌발적인 장애 상황에서도 클러스터의 회복탄력성(Resilience)을 근본적으로 보장하는 중대한 설정이다.

## **종합 구성 명세서: The Ultimate Values.yaml**

지금까지 분석한 구조적 한계 극복, 능동적 리더 이양 스크립트, Kubernetes 라이프사이클 조율, Karpenter 인프라 정책 매핑, 그리고 Multi-AZ 네트워크 튜닝 기법을 하나로 통합하여, 롤링 업그레이드나 동적 노드 환경에서 인간의 개입 없이 다운타임을 제거하는 궁극적인 Bitnami etcd Helm Chart 구성을 도출할 수 있다.  
이 구성 파일(values.yaml)은 조직의 프로덕션 환경에 즉시 적용될 수 있는 검증된 명세이다.  
`# 클러스터 크기 (Quorum = 2)`  
`replicaCount: 3`

`# 1. 고가용성을 위한 파드 분산 및 스토리지 보존`  
`# 노드 및 AZ 레벨에서 파드가 겹치지 않도록 강제`  
`podAntiAffinityPreset: hard`  
`topologySpreadConstraints:`  
  `- maxSkew: 1`  
    `topologyKey: topology.kubernetes.io/zone`  
    `whenUnsatisfiable: DoNotSchedule`  
    `labelSelector:`  
      `matchLabels:`  
        `app.kubernetes.io/name: etcd`

`# 롤링 업데이트나 파드 재시작 시 기존 데이터를 반드시 보존`  
`persistentVolumeClaimRetentionPolicy:`  
  `enabled: true`  
  `whenScaled: Retain`  
  `whenDeleted: Retain`

`# 2. PodDisruptionBudget (Karpenter에 대한 축출 방어선)`  
`pdb:`  
  `create: true`  
  `minAvailable: 2`

`# 3. K8s 파드 레벨 종료 유예 시간 (충분한 시간 확보)`  
`# 참고: Karpenter NodePool의 terminationGracePeriod는 이 값보다 큰 600s 이상으로 설정되어야 함`  
`terminationGracePeriodSeconds: 90`

`# 4. Multi-AZ 환경에 최적화된 네트워크/선거 타임아웃 튜닝`  
`extraEnvVars:`  
  `- name: ETCD_HEARTBEAT_INTERVAL`  
    `value: "250"`  
  `- name: ETCD_ELECTION_TIMEOUT`  
    `value: "2500"`

`# 5. Bitnami 기본 맹점 해결: 강제 멤버 탈퇴 스크립트 비활성화`  
`removeMemberOnContainerTermination: false`

`# 6. 무중단 리더 이양을 위한 커스텀 PreStop 훅 구성`  
`lifecycleHooks:`  
  `preStop:`  
    `exec:`  
      `command:`  
        `- /bin/bash`  
        `- -c`  
        `- |`  
          `set -o pipefail`  
          `# Bitnami 스크립트 라이브러리 소싱 (환경 변수 및 인증 정보 로드)`  
          `source /opt/bitnami/scripts/libetcd.sh`  
            
          `echo "Initiating preStop hook for zero-downtime shutdown..."`  
            
          `# 현재 노드가 리더인지 검증`  
          `# 주의: etcdctl의 출력 포맷을 일관되게 파싱하기 위해 simple 대신 파이프라인 처리에 유리한 형식 활용`  
          `AM_LEADER=$(etcdctl endpoint status | grep $(hostname) | cut -d ',' -f 5 | tr -d ' ')`  
            
          `if]; then`  
            `echo "Current node is the LEADER. Finding a follower for transfer..."`  
            `# 본인이 아닌 노드 중 응답 가능한 정상 상태의 멤버 ID 추출`  
            `NEW_LEADER=$(etcdctl endpoint status | grep -v $(hostname) | cut -d ',' -f 2 | tr -d ' ' | tail -n '-1')`  
              
            `if]; then`  
              `echo "Executing move-leader to member ID: $NEW_LEADER"`  
              `etcdctl move-leader $NEW_LEADER`  
                
              `# 네트워크 드레인: 클라이언트가 새로운 리더로 접속을 전환하도록 15초 대기`  
              `echo "Leadership transferred. Sleeping 15s for connection draining..."`  
              `sleep 15`  
            `else`  
              `echo "Error: No active follower found. Falling back to default shutdown."`  
              `sleep 5`  
            `fi`  
          `else`  
            `echo "Current node is a FOLLOWER. Sleeping 5s for connection draining..."`  
            `sleep 5`  
          `fi`

### **무중단 롤링 업그레이드 시나리오 검증**

위 구성이 적용된 상태에서 Helm 차트 업그레이드나 Karpenter의 노드 통합(Consolidation) 이벤트가 발생할 때의 시스템 동작 흐름은 완벽하게 자동화된다.

1. **Eviction 트리거**: Kube-scheduler가 리더 역할을 하고 있는 etcd-0 파드에 축출(Eviction) 명령을 내린다. 이때 PDB(minAvailable: 2)에 의해 다른 2개의 파드가 정상 상태(Ready)임을 확인하고 나서야 축출이 허용된다.  
2. **PreStop 훅 및 리더 이전**: etcd-0 파드가 SIGTERM을 받기 직전 PreStop 훅이 실행된다. 스크립트는 etcd-0이 리더임을 인지하고 즉시 etcd-1(또는 etcd-2)로 리더십을 이전한다(move-leader).  
3. **트래픽 단절 없는 전환**: 리더십 이전은 밀리초 내에 이루어지므로 클라이언트는 선거 타임아웃을 기다릴 필요 없이 etcd-1로 즉각 쓰기 요청을 보낼 수 있다. sleep 15 동안 Kube-proxy의 규칙이 갱신되며, 기존 연결은 안전하게 닫힌다.  
4. **안전한 파드 종료 및 보존**: 유예 시간이 끝나고 컨테이너가 종료된다. removeMemberOnContainerTermination: false 설정으로 인해 멤버십은 파괴되지 않으며, PV(Persistent Volume)에 저장된 데이터는 온전히 보존된다.  
5. **재합류(Re-join) 및 복구**: 새로운 노드에 etcd-0이 다시 스케줄링된다. 기존 PV를 마운트한 상태로 기동되며, 남아있는 멤버십 정보를 바탕으로 클러스터에 팔로워로서 자연스럽게 재합류한다. 그동안 밀린 로그(Raft Entry)를 현재 리더로부터 스냅샷 동기화 받아 최신 상태를 따라잡게 된다.

이 모든 과정에서 관리자가 SSH로 접속하거나, 에러 로그를 확인하고 수동으로 member add/remove를 타이핑하는 등의 **휴먼 리소스(Human Resource)가 포함된 작업은 단 한 번도 발생하지 않는다**. 시스템은 스스로 치유(Self-healing)되고 라우팅을 조율하며 무중단으로 업그레이드를 완수한다.

## **결론 및 제언**

본 연구 분석 결과, Kubernetes EKS 환경과 동적 노드 프로비저닝을 주도하는 Karpenter 아키텍처 하에서 Bitnami etcd Helm 차트를 운영할 때 발생하는 롤링 업그레이드 및 리더 파드 삭제에 따른 다운타임 문제는 구조적으로, 그리고 완전히 자동화된 방식으로 해결할 수 있음이 명확히 규명되었다.  
초기 도입부에서 제기되었던 질의인 "리더가 죽어도 다운타임이 없도록 자연스러운 방안이 존재하는가?"와 "안된다면 휴먼 리소스가 포함된 작업을 해야 하는가?"에 대한 해답은 자명하다. 인적 개입은 전혀 필요하지 않으며, 네이티브 Kubernetes 라이프사이클 훅과 클러스터링 명령어의 정교한 조합만으로 무중단(Zero-Downtime)을 달성할 수 있다.  
이러한 무중단 상태를 달성하기 위해 조직이 취해야 하는 필수적인 기술적 조치는 다음과 같이 요약된다.  
첫째, Bitnami 차트가 가진 공격적인 prestop.sh 멤버 삭제 로직의 맹점을 인지하고 removeMemberOnContainerTermination: false를 통해 상태 보존성을 확립해야 한다. 이 설정이 없다면 어떠한 무중단 스크립트도 결국 CrashLoopBackOff 에러와 데이터 고립이라는 파국으로 이어질 뿐이다.  
둘째, 타임아웃에 의존하는 수동적 Raft 선거 방식을 탈피하여, etcdctl move-leader 명령을 커스텀 PreStop 훅 내에 삽입함으로써 현재 리더가 능동적이고 선제적으로 권한을 이양하도록 강제해야 한다. 이 과정에 수반되는 15초가량의 드레인(Draining) 대기 시간은 네트워크 트래픽의 매끄러운 전환을 보장하는 핵심 기술이다.  
셋째, ETCD 레벨의 설정에만 매몰되지 말고 인프라스트럭처 레벨(Karpenter)의 라이프사이클 정책과 K8s 레벨(PDB)의 방어 기제를 유기적으로 매핑해야 한다. Karpenter NodePool의 terminationGracePeriod가 파드의 terminationGracePeriodSeconds를 넉넉히 수용할 수 있도록 상향 조정되어야만 강제 축출로 인한 데이터 손실을 막을 수 있다.  
넷째, Multi-AZ 클라우드 인프라의 물리적 한계를 고려하여 heartbeat-interval과 election-timeout 파라미터를 현실적으로 튜닝함으로써, 네트워크 지터로 인한 불필요한 선거(Spurious Election)를 차단하고 클러스터 전반의 회복탄력성을 극대화해야 한다.  
현대 클라우드 네이티브 아키텍처에서 인프라는 영원불멸한 애완동물(Pet)이 아니라 언제든 교체 가능한 가축(Cattle)으로 다루어져야 한다. State를 보유하고 있는 데이터베이스나 분산 코디네이터도 예외는 아니다. 본 보고서에서 제시된 아키텍처와 구성 명세서를 시스템에 온전히 반영함으로써, 조직은 빈번한 인프라스트럭처의 재배치나 스팟 인스턴스의 회수 압박 속에서도 비즈니스 연속성을 해치지 않는 극단적인 수준의 고가용성과 진정한 의미의 무인화(Human-free) 운영 체계를 성취할 수 있을 것이다.

#### **참고 자료**

1\. etcd 8.9.0 · bitnami/bitnami \- Artifact Hub, https://artifacthub.io/packages/helm/bitnami/etcd/8.9.0?modal=values 2\. etcd 9.8.0 · bitnami/bitnami \- Artifact Hub, https://artifacthub.io/packages/helm/bitnami/etcd/9.8.0 3\. charts/bitnami/etcd/README.md at main \- GitHub, https://github.com/bitnami/charts/blob/main/bitnami/etcd/README.md 4\. Manage scale-to-zero scenarios with Karpenter and Serverless | Containers \- AWS, https://aws.amazon.com/blogs/containers/manage-scale-to-zero-scenarios-with-karpenter-and-serverless/ 5\. Scaling Kubernetes Smarter with Karpenter | by Freshworks Engineering \- Medium, https://medium.com/freshworks-engineering-blog/karpenter-89653a22f4bf 6\. Disruption | Karpenter, https://karpenter.sh/docs/concepts/disruption/ 7\. How to Optimize Karpenter for Efficiency and Cost \- PerfectScale, https://www.perfectscale.io/blog/karpenter-cost-optimization 8\. Specifying a Disruption Budget for your Application \- Kubernetes, https://kubernetes.io/docs/tasks/run-application/configure-pdb/ 9\. Pod Disruption Budget vs NodePool Disruption Budget? \- Vijay Kodam, https://vijay.eu/posts/pod-disruption-budget-vs-nodepool-disruption-budget/ 10\. Frequently Asked Questions (FAQ) \- etcd, https://etcd.io/docs/v3.2/faq/ 11\. Performing a Rolling Update \- Kubernetes, https://kubernetes.io/docs/tutorials/kubernetes-basics/update/update-intro/ 12\. Why Your Kubernetes Rolling Updates Still Cause Downtime | by Guduru sai krishna, https://medium.com/@gudurusaikrishna66/why-your-kubernetes-rolling-updates-still-cause-downtime-ab6af7b963e4 13\. Rolling Update Usually results in etcd/api-server Related Downtime · Issue \#9464 · kubernetes/kops \- GitHub, https://github.com/kubernetes/kops/issues/9464 14\. Advanced Kubernetes Interview Questions: The Complete Guide to Production Troubleshooting, Architecture, and Design Patterns \- Living Devops, https://livingdevops.com/kubernetes/advanced-kubernetes-interview-questions-the-complete-guide-to-production-troubleshooting-architecture-and-design-patterns/ 15\. Runtime reconfiguration \- etcd, https://etcd.io/docs/v3.4/op-guide/runtime-configuration/ 16\. Tuning \- etcd, https://etcd.io/docs/v3.4/tuning/ 17\. Kubernetes in Production: What You Should Know \- Aqua Security, https://www.aquasec.com/cloud-native-academy/kubernetes-in-production/kubernetes-in-production-what-you-should-know/ 18\. Operating etcd clusters for Kubernetes, https://kubernetes.io/docs/tasks/administer-cluster/configure-upgrade-etcd/ 19\. etcd \- move leader away \- gists · GitHub, https://gist.github.com/clementnuss/1d63abca2e2bea08963a3453d61e89e8 20\. etcd/etcdctl/README.md at main \- GitHub, https://github.com/etcd-io/etcd/blob/main/etcdctl/README.md?plain=1 21\. Migrating etcd between cloud Kubernetes clusters with no downtime | Tech blog \- Palark, https://palark.com/blog/etcd-in-kubernetes-migration-tutorial/ 22\. \[bitnami/etcd\] Cluster does not start from etcd · Issue \#15790 \- GitHub, https://github.com/bitnami/charts/issues/15790 23\. etcd 9.0.0 · bitnami/bitnami \- Artifact Hub, https://artifacthub.io/packages/helm/bitnami/etcd/9.0.0 24\. \[bitnami/etcd\] preStop fails · Issue \#7048 \- GitHub, https://github.com/bitnami/charts/issues/7048 25\. \[bitnami/etcd\] Cluster does not start from etcd · Issue \#19130 \- GitHub, https://github.com/bitnami/charts/issues/19130 26\. ETCD cluster loses member on GKE every day at 5am · Issue \#14542 \- GitHub, https://github.com/etcd-io/etcd/issues/14542 27\. \[bitnami/etcd\] pod rejoin fails after removing old member · Issue \#14731 \- GitHub, https://github.com/bitnami/charts/issues/14731 28\. etcd \- Bitnami \- Artifact Hub, https://artifacthub.io/packages/helm/bitnami/etcd?modal=values 29\. \[bitnami/etcd\] Error "Cluster not healthy, not adding self to cluster for now" \#23531 \- GitHub, https://github.com/bitnami/containers/issues/23531 30\. bitnami/etcd/data/member\_id: No such file or directory · Issue \#1037 \- GitHub, https://github.com/bitnami/charts/issues/1037 31\. \[bitnami/etcd\] ETCD cluster fails after restart due to member remove \#5443 \- GitHub, https://github.com/bitnami/charts/issues/5443 32\. \[bitnami/etcd\] member can't join cluster \#16071 \- GitHub, https://github.com/bitnami/charts/issues/16071 33\. APISIX微服务网关实战指南：轻松掌握架构、组件与部署(上) 原创 \- CSDN博客, https://blog.csdn.net/qq\_40477248/article/details/144231784 34\. Troubleshooting | Milvus Documentation, https://milvus.io/docs/troubleshooting.md 35\. Maintenance \- etcd, https://etcd.io/docs/v3.3/op-guide/maintenance/ 36\. v3.5 docs, https://docs.tecnisys.com.br/pgsys-ecosystem/en/pdf/etcd/3.5/etcd-3.5.pdf 37\. Container Lifecycle Hooks \- Kubernetes, https://kubernetes.io/docs/concepts/containers/container-lifecycle-hooks/ 38\. Gracefully Terminating Pods in Kubernetes — Part 2: PreStop Hooks | by Amila De Silva, https://jaadds.medium.com/gracefully-terminating-pods-in-kubernetes-part-2-prestop-hooks-41fbd3a5318e 39\. How to save the database \- etcd, https://etcd.io/docs/v3.5/tutorials/how-to-save-database/ 40\. How to check Cluster status \- etcd, https://etcd.io/docs/v3.5/tutorials/how-to-check-cluster-status/ 41\. How to change a leader in etcd cluster? \- Stack Overflow, https://stackoverflow.com/questions/42580821/how-to-change-a-leader-in-etcd-cluster 42\. Interacting with etcd, https://etcd.io/docs/v3.4/dev-guide/interacting\_v3/ 43\. IBM Cloud Private System Administrator s Guide, https://www.redbooks.ibm.com/redbooks/pdfs/sg248440.pdf 44\. etcdctl member list should return member IDs in a consistent format \#9535 \- GitHub, https://github.com/etcd-io/etcd/issues/9535 45\. etcdctl(1) — etcd-client — Debian unstable \- Debian Manpages, https://manpages.debian.org/unstable/etcd-client/etcdctl.1.en.html 46\. karpenter/designs/nodeclaim-termination-grace-period.md at main \- GitHub, https://github.com/kubernetes-sigs/karpenter/blob/main/designs/nodeclaim-termination-grace-period.md 47\. Karpenter \- Skyscrapers Docs, https://docs.skyscrapers.eu/docs/explanation/kubernetes/karpenter/ 48\. Karpenter at Beekeeper by LumApps: Fun Stories | by Sanadhi Sutandi \- Medium, https://medium.com/beekeeper-technology-blog/karpenter-at-beekeeper-by-lumapps-fun-stories-7c55656f02b8 49\. Massive scaling and anomalous behaviors with the new forceful disruption method · Issue \#7632 · aws/karpenter-provider-aws \- GitHub, https://github.com/aws/karpenter-provider-aws/issues/7632 50\. How to Implement Rolling Updates with Zero Downtime \- OneUptime, https://oneuptime.com/blog/post/2026-01-25-kubernetes-rolling-updates-zero-downtime/view 51\. Simplify node lifecycle with managed node groups \- Amazon EKS, https://docs.aws.amazon.com/eks/latest/userguide/managed-node-groups.html 52\. Kubernetes best practices: terminating with grace | Google Cloud Blog, https://cloud.google.com/blog/products/containers-kubernetes/kubernetes-best-practices-terminating-with-grace 53\. Decoding the pod termination lifecycle in Kubernetes: a comprehensive guide | CNCF, https://www.cncf.io/blog/2024/12/19/decoding-the-pod-termination-lifecycle-in-kubernetes-a-comprehensive-guide/ 54\. charts/bitnami/etcd/values.yaml at main \- GitHub, https://github.com/bitnami/charts/blob/main/bitnami/etcd/values.yaml 55\. NodePools \- Karpenter, https://karpenter.sh/docs/concepts/nodepools/ 56\. Karpenter forcefully terminating pods : r/kubernetes \- Reddit, https://www.reddit.com/r/kubernetes/comments/1l1o1dg/karpenter\_forcefully\_terminating\_pods/ 57\. How to Create Spot Instance Strategy \- OneUptime, https://oneuptime.com/blog/post/2026-01-30-spot-instance-strategy/view 58\. How to Implement Spot Instance Interruption Handling with Node Termination Handler on Kubernetes \- OneUptime, https://oneuptime.com/blog/post/2026-02-09-spot-instance-termination-handler/view 59\. Assign Pods to Nodes with Bitnami Helm Chart Affinity Rules \- Broadcom Techdocs, https://techdocs.broadcom.com/us/en/vmware-tanzu/bitnami-secure-images/bitnami-secure-images/services/bsi-doc/apps-tutorials-assign-pod-nodes-helm-affinity-rules-index.html 60\. Amazon EKS \- Best Practices Guide, https://docs.aws.amazon.com/pdfs/eks/latest/best-practices/eks-bpg.pdf 61\. What Are The Best Practices For Setting Up Karpenter? \- nOps, https://www.nops.io/blog/best-practices-for-setting-up-karpenter/ 62\. Troubleshooting | Karpenter, https://karpenter.sh/docs/troubleshooting/ 63\. Kubernetes Scheduling: podAntiAffinity vs. topologySpreadConstraints \- DEV Community, https://dev.to/hstiwana/kubernetes-scheduling-podantiaffinity-vs-topologyspreadconstraints-41j4 64\. make topologySpreadConstraints smoother to use · Issue \#18882 · bitnami/charts \- GitHub, https://github.com/bitnami/charts/issues/18882 65\. Tuning | etcd, https://etcd.io/docs/v2.3/tuning/ 66\. How can we modify the heartbeat synchronization time of the etcd cluster on Kubernetes \- Server Fault, https://serverfault.com/questions/1067916/how-can-we-modify-the-heartbeat-synchronization-time-of-the-etcd-cluster-on-kube 67\. bug: One of the three etcd nodes is broken (once every two weeks) · Issue \#15065 \- GitHub, https://github.com/etcd-io/etcd/issues/15065 68\. \[bitnami/etcd\] etcd pods are unable to join existing cluster on node drain \#16069 \- GitHub, https://github.com/bitnami/charts/issues/16069