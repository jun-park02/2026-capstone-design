# Fire Image DB Design

현재 구조를 보면, 이미지 관련 원천 데이터는 `mavlink/raw_receiver.py`에서 `event_id`, `image_id`, `captured_at`, `lat/lon`, `confidence`, `image_name` 같은 필드를 만들고, 이미지 바이트는 같은 프로세스에서 바로 S3에 업로드한다. DB는 SQLAlchemy/Alembic이 이미 있으므로, `이벤트`와 `이미지 파일`을 분리한 2테이블 구조를 추천한다.

## 추천 구조

- `fire_events`
- `fire_event_images`

이렇게 나누는 이유는 `event_id`와 `image_id`가 이미 분리돼 있고, 나중에 한 이벤트에 이미지가 여러 장 붙어도 자연스럽게 확장되기 때문이다.

```sql
CREATE TABLE fire_events (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  event_id VARCHAR(64) NOT NULL UNIQUE,
  redis_stream_id VARCHAR(32) NULL UNIQUE,
  received_at DATETIME(6) NOT NULL,
  captured_at DATETIME(6) NULL,
  lat DECIMAL(10,7) NULL,
  lon DECIMAL(10,7) NULL,
  alt DECIMAL(8,2) NULL,
  confidence DECIMAL(5,4) NULL,
  src_ip VARCHAR(45) NULL,
  src_port INT UNSIGNED NULL,
  dst_port INT UNSIGNED NULL,
  raw_payload JSON NOT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)
);

CREATE TABLE fire_event_images (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  fire_event_id BIGINT UNSIGNED NOT NULL,
  image_uid VARCHAR(64) NOT NULL,
  original_filename VARCHAR(255) NOT NULL,
  source_local_path VARCHAR(1024) NULL,
  file_ext VARCHAR(16) NULL,
  content_type VARCHAR(100) NULL,
  file_size_bytes BIGINT UNSIGNED NULL,
  checksum_sha256 CHAR(64) NULL,
  chunk_total INT UNSIGNED NULL,

  storage_provider VARCHAR(20) NOT NULL DEFAULT 's3',
  bucket VARCHAR(255) NULL,
  object_key VARCHAR(1024) NULL,
  object_version_id VARCHAR(255) NULL,
  etag VARCHAR(255) NULL,

  upload_status VARCHAR(20) NOT NULL DEFAULT 'pending',
  upload_error TEXT NULL,
  uploaded_at DATETIME(6) NULL,

  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),

  UNIQUE KEY uq_event_image (fire_event_id, image_uid),
  UNIQUE KEY uq_bucket_key (bucket, object_key),
  CONSTRAINT fk_fire_event_images_event
    FOREIGN KEY (fire_event_id) REFERENCES fire_events(id)
);
```

## `fire_event_images` 필드 설명

이 테이블은 "어떤 화재 이벤트에 속한 이미지인지"와 "그 이미지가 S3에 어떻게 저장됐는지"를 기록하는 용도다.

### 관계/식별 필드

- `id`: `fire_event_images` 테이블 자체의 내부 PK다. DB가 관리하는 번호다.
- `fire_event_id`: 부모 이벤트인 `fire_events.id`를 가리키는 FK다. 이 이미지가 어떤 화재 이벤트에 속하는지 연결한다.
- `image_uid`: 원본 payload의 `image_id`다. 외부 시스템이 준 이미지 고유값이다.
- `UNIQUE (fire_event_id, image_uid)`: 같은 이벤트 안에서 같은 이미지가 중복 저장되지 않도록 막는다.

### 원본 이미지 메타데이터

- `original_filename`: 원래 파일명이다. 예: `abc123.jpg`
- `source_local_path`: 로컬에 저장됐던 경로다. 예: `/app/images/abc123.jpg`
- `file_ext`: 확장자다. 예: `jpg`, `png`
- `content_type`: MIME 타입이다. 예: `image/jpeg`
- `file_size_bytes`: 파일 크기다. 사용자 응답이나 검증에 유용하다.
- `checksum_sha256`: 파일 해시값이다. 중복 검사나 무결성 확인에 유용하다.
- `chunk_total`: 원본 전송이 청크 기반일 때 총 청크 수다. 디버깅용으로 유용하다.

### S3 저장 메타데이터

- `storage_provider`: 저장소 종류다. 지금 구조에서는 보통 `s3`로 두면 된다.
- `bucket`: S3 버킷 이름이다.
- `object_key`: 버킷 안의 실제 객체 경로다. 예: `fire-detect/abc123.jpg`
- `object_version_id`: S3 버전 관리가 켜져 있을 때 객체 버전 ID다.
- `etag`: S3가 반환하는 객체 식별값이다. 업로드 검증에 참고할 수 있다.
- `UNIQUE (bucket, object_key)`: 같은 S3 객체가 중복 등록되지 않도록 막는다.

### 업로드 상태 관리

- `upload_status`: 업로드 상태다. 예: `pending`, `uploaded`, `failed`, `deleted`
- `upload_error`: 업로드 실패 시 에러 메시지를 저장하는 필드다.
- `uploaded_at`: 실제 S3 업로드가 완료된 시각이다.

### 감사/추적용 시간 필드

- `created_at`: 이 DB 레코드가 처음 만들어진 시각이다.
- `updated_at`: 이 레코드가 마지막으로 수정된 시각이다.

### 최소 구성으로 시작하려면

초기 버전에서는 아래 필드만 있어도 충분히 운영할 수 있다.

- `id`
- `fire_event_id`
- `image_uid`
- `original_filename`
- `content_type`
- `file_size_bytes`
- `bucket`
- `object_key`
- `upload_status`
- `uploaded_at`
- `created_at`
- `updated_at`

## 핵심 포인트

- DB에는 `S3 URL`보다 `bucket + object_key`를 저장하는 것이 좋다.
- `presigned URL`은 만료되므로 DB에 저장하지 말고, 요청 시점에 생성하는 편이 안전하다.
- 로컬 경로를 쓰지 않는 구조라면 `image_path`는 아예 저장하지 않거나, 디버깅이 꼭 필요할 때만 선택적으로 남기는 것이 좋다.
- `raw_payload JSON`은 꼭 남기는 것이 좋다. 나중에 payload 필드가 늘어나도 마이그레이션 부담이 줄어든다.
- 조회가 많을 컬럼만 정규화해서 빼면 된다. 예시는 `captured_at`, `confidence`, `lat`, `lon`, `upload_status`다.

## 저장 흐름

1. Redis 이벤트 수신
2. `fire_events`를 `event_id` 기준으로 upsert
3. `fire_event_images`를 `(fire_event_id, image_uid)` 기준으로 upsert하고 `upload_status='pending'`로 저장
4. S3 업로드 성공 시 `bucket`, `object_key`, `etag`, `uploaded_at`, `upload_status='uploaded'` 업데이트
5. 업로드 실패 시 `upload_status='failed'`, `upload_error` 저장

## 사용자 제공 방식

- 비공개 이미지면 API에서 DB 조회 후 presigned URL 생성
- 공개 이미지면 API에서 `bucket`과 `object_key`를 바탕으로 CDN 또는 public URL 생성
- 응답용으로 `s3_image_url`을 내려주는 것은 괜찮지만, 영구 저장 기준값으로 삼는 것은 추천하지 않는다

## 결론

지금 단계에서는 `fire_events`와 `fire_event_images`의 2테이블 구조가 가장 균형이 좋다. 현재 payload 구조와도 잘 맞고, 나중에 조회 API, 업로드 재시도, 이미지 다건 처리까지 확장하기 쉽다.
