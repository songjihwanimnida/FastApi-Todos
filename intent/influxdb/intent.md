# Intent: JMeter 부하 테스트 결과를 InfluxDB에 저장하기
Author: songjihwan. Date: 2026-11-07. Status: draft.

## Problem
과제로 InfluxDB를 써 봐야 하는데, 지금 모니터링 구성에는 InfluxDB가 없다.
JMeter 부하 테스트 결과는 실행이 끝난 뒤 `results.jtl` 파일과 HTML 리포트로만 남는다. 테스트 도중의 응답 시간, 처리량, 에러를 Grafana에서 볼 수 없다.
JMeter를 한 번 돌리면 요청 30개가 10초 만에 끝나서, 그래프로 보기에도 데이터가 너무 적다.

## Proposed outcome
- InfluxDB 1.x가 기존 모니터링 스택(Prometheus, Grafana)과 함께 docker compose로 뜬다.
- JMeter를 돌리면 결과가 테스트 도중 실시간으로 InfluxDB에 쌓인다.
- Grafana에 InfluxDB 데이터 소스가 자동으로 등록되어 있고, JMeter 대시보드(5496)를 import하면 응답 시간, 처리량, 에러율이 보인다.
- 실행할 때 사용자 수, 반복 횟수, 램프업 시간을 바꿀 수 있다. 바꾸지 않으면 지금과 같은 양으로 돈다.
- JMeter를 여러 번 다시 돌려도 이전 결과 파일 때문에 실패하지 않는다.
- 리눅스 서버에서 git pull과 docker compose up만으로 같은 결과를 볼 수 있다. 과제 화면은 서버 Grafana에서 캡처한다.

## Out of scope
- 앱(`main.py`) 코드 변경. 앱이 InfluxDB에 직접 기록하는 기능도 넣지 않는다.
- Prometheus 메트릭을 InfluxDB로 옮기거나 복제하기
- InfluxDB 2.x, 3.x, Flux 쿼리
- Grafana 대시보드를 파일로 등록하기 (대시보드는 UI에서 import)
- 배포 파이프라인 설정 변경 (저장소 밖에 있음)
- 버전 태그, 릴리즈 노트 (원할 때 따로)

## Affected users and systems
- 사용자: 과제로 부하 테스트 결과를 확인하는 개발자(본인)
- `docker-compose.yml` (influxdb 서비스, grafana 마운트, jmeter 실행 옵션)
- `jmeter/fastapi_test_plan.jmx` (결과 전송, 부하량 설정)
- 새 Grafana 데이터 소스 설정 파일, `.gitignore`, `CLAUDE.md`
- 리눅스 서버의 모니터링 스택

## Constraints
- 다른 서비스처럼 이미지 버전을 고정하고 권한을 최소로 둔다.
- InfluxDB 1.x는 로그인이 없으므로 외부 포트를 열지 않는다.
- Grafana에 이미 있는 Prometheus 데이터 소스와 대시보드가 사라지면 안 된다.
- 기본 실행(옵션 없음)의 부하량은 지금과 같아야 한다.
- 서버에서 파일을 직접 고치지 않는다. 모든 수정은 저장소에서 하고 main에 머지한 뒤 서버가 pull한다.

## Open questions
- 서버의 모니터링 스택을 직접 compose로 띄웠는지, 파이프라인이 띄웠는지 (서버에서 grafana 컨테이너의 compose 폴더를 확인해 판단)
