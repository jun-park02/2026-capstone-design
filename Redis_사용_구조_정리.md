# Redis 사용 구조 정리

이 프로젝트에서 Redis는 영구 저장소라기보다 **실시간 메시지 버스 + 최신 상태 캐시 + 지도용 경로 캐시** 역할을 한다. 화재 이벤트의 최종 기록은 MySQL `fire_events` 계열 테이블에 저장되고, MAVLink 텔레메트리 기록은 MySQL `drone_telemetry` 테이블에도 저장된다.

## 전체 흐름

```text
MAVLink 송신기/드론
  -> mavlink/receiver.py
  -> Redis Stream mystream
  -> backend RedisStreamConsumer
     -> Redis List drone:path:<system_id> -> /map/overview, /map/drone-paths
     -> MySQL drone_telemetry             -> /drones/telemetry
```

```text
화재 이미지 HTTP 업로드
  -> mavlink/raw_receiver.py
  -> Redis Stream fire_detect
  -> backend FireDetectListener
  -> S3 업로드 + MySQL 저장
  -> /raw/latest, /raw/latest/live, /map/fire-detections, /map/overview
```

## Redis 키 구조

| 키 | 자료구조 | 작성자 | 용도 |
| --- | --- | --- | --- |
| `mystream` | Redis Stream | `mavlink/receiver.py` | MAVLink 원본 메시지 저장 |
| `fire_detect` | Redis Stream | `mavlink/raw_receiver.py` | HTTP 업로드로 받은 화재 이미지 이벤트 저장 |
| `drone:last_seen` | Sorted Set | `mavlink/receiver.py` | 드론별 마지막 HEARTBEAT 수신 시각 저장 |
| `drone:status:<system_id>` | Hash | `mavlink/receiver.py` | 드론별 최신 HEARTBEAT 상태 저장 |
| `drone:path:ids` | Set | `backend/app/redis_consumer.py` | 경로 캐시가 존재하는 드론 ID 목록 |
| `drone:path:<system_id>` | List | `backend/app/redis_consumer.py` | 지도 표시용 드론별 위치 경로 |

## MySQL에 저장되는 텔레메트리

`backend/app/redis_consumer.py`는 `mystream` 메시지를 처리할 때 Redis 경로 캐시를 만들면서 동시에 MySQL `drone_telemetry` 테이블에도 row를 저장한다.

| 컬럼 | 설명 |
| --- | --- |
| `redis_stream_id` | Redis Stream 메시지 ID. 중복 저장 방지용 unique key |
| `message_type` | MAVLink 메시지 타입. 예: `GLOBAL_POSITION_INT`, `HEARTBEAT`, `ATTITUDE` |
| `system_id`, `component_id` | MAVLink 드론/컴포넌트 ID |
| `telemetry_at` | receiver가 메시지를 Redis에 넣은 시각 |
| `lat`, `lon`, `alt`, `relative_alt`, `heading`, `time_boot_ms` | 위치 메시지에서 추출한 주요 필드 |
| `raw_payload` | Redis에 저장된 원본 payload |

실시간 지도는 여전히 Redis `drone:path:*`를 읽고, 과거 기록 조회나 화재 시각 주변 텔레메트리 조회는 `drone_telemetry`를 사용할 수 있다.

## Redis에 쓰는 흐름

### MAVLink 메시지

`mavlink/receiver.py`가 UDP `14550`으로 MAVLink 메시지를 받고 Redis Stream `mystream`에 저장한다.

```text
XADD mystream MAXLEN ~ 10000 payload=<json>
```

현재 receiver는 `MAVLINK_SAMPLE_INTERVAL_SEC=2` 기본값 기준으로 같은 드론/컴포넌트/메시지 타입을 2초에 한 번만 Redis에 저장한다.

### 드론 최신 상태

`HEARTBEAT` 메시지를 받으면 Redis에 드론별 상태가 따로 저장된다.

```text
ZADD drone:last_seen <last_seen_ts> <system_id>
HSET drone:status:<system_id> system_status ... last_seen_ts ...
EXPIRE drone:status:<system_id> 86400
```

### 지도용 경로 캐시

FastAPI 시작 시 `RedisStreamConsumer`가 `mystream`을 읽고, `GLOBAL_POSITION_INT` 메시지만 뽑아서 지도 경로 캐시를 만든다.

```text
SADD drone:path:ids <system_id>
RPUSH drone:path:<system_id> <point-json>
LTRIM drone:path:<system_id> -1000 -1
EXPIRE drone:path:<system_id> 86400
```

같은 consumer가 처리한 MAVLink payload는 `drone_telemetry` 테이블에도 batch insert된다. DB 저장 실패가 발생해도 Redis 경로 캐시는 계속 갱신되도록 되어 있어 실시간 지도 응답을 막지 않는다.

### 화재 감지 이벤트

`mavlink/raw_receiver.py`는 FastAPI 서버로 실행되며 `POST /fire-detections/upload`에서 `multipart/form-data` 이미지를 받는다. 업로드된 이미지를 공유 볼륨 `/app/images`에 저장한 뒤 `fire_detect` Stream에 완료 이벤트를 저장한다.

```text
XADD fire_detect MAXLEN ~ 10000 payload=<json>
```

이후 FastAPI의 `FireDetectListener`가 `fire_detect`를 읽고 S3 업로드, MySQL 저장, 확인 메일 발송을 처리한다.

구 UDP 청크 수신 방식은 `mavlink/legacy/raw_udp_receiver.py`에 보관되어 있다.

## Redis에서 데이터를 읽는 엔드포인트

| 엔드포인트 | Redis에서 읽는 데이터 | 설명 |
| --- | --- | --- |
| `GET /mavlink/latest` | `mystream` | 최신 MAVLink 메시지 1건 조회 |
| `GET /raw/latest` | `fire_detect` | 최신 화재 감지 이벤트 1건 조회 |
| `GET /map/drone-paths` | `drone:path:ids`, `drone:path:<system_id>` | 드론 경로 캐시 조회. 캐시가 없으면 `mystream` fallback scan |
| `GET /map/overview` | `drone:path:ids`, `drone:path:<system_id>` | 드론 경로는 Redis에서, 화재 마커는 MySQL에서 가져와 합쳐 반환 |
| `GET /drones/active/count` | `drone:last_seen`, `drone:status:<system_id>` | 최근 `timeout_sec` 안에 HEARTBEAT를 보낸 active 드론 수 계산 |

## Redis를 직접 읽지 않는 관련 엔드포인트

| 엔드포인트 | 데이터 출처 | 비고 |
| --- | --- | --- |
| `GET /map/fire-detections` | MySQL `fire_events` | Redis 사용 없음 |
| `GET /drones/telemetry` | MySQL `drone_telemetry` | Redis 사용 없음. 저장된 MAVLink 텔레메트리 기록 조회 |
| `GET /raw/latest/live` | 메모리 캐시 `runtime.fire_listener.last_event` + MySQL | Redis Stream을 직접 재조회하지 않음 |
| `GET /fire-events/*` | MySQL | 확인 메일, 상태 카운트, 확인 링크 처리 |
| `GET /notification-recipients` / `POST /notification-recipients` | MySQL | Redis 사용 없음 |
| `GET /health` | 메모리 상태 | Redis client와 listener 상태만 표시 |

## `/map/overview` 데이터 출처

`/map/overview`는 두 종류의 데이터를 합친다.

```text
drone_paths:
  Redis drone:path:* 캐시
  캐시가 없으면 Redis Stream mystream fallback scan

fire_detections:
  MySQL fire_events
```

즉 `/map/overview`의 `drone_paths`는 Redis 기반이고, `fire_detections`는 MySQL 기반이다.

## 주의할 점

- `mystream`, `fire_detect`는 `MAXLEN ~ 10000`으로 제한되어 오래된 메시지는 Redis에서 사라질 수 있다.
- `drone:path:*`, `drone:status:*`, `drone:path:ids`는 기본 TTL이 86400초다.
- `docker-compose.yml`의 Redis 서비스에는 별도 volume이 없어 컨테이너가 초기화되면 Redis 데이터가 사라질 수 있다.
- MAVLink 텔레메트리는 `drone_telemetry` 테이블에 저장되지만, `/map/overview`의 실시간 경로는 성능을 위해 Redis에서 읽는다.
