# Fire Image DB Design

현재 구조를 보면, 이미지 관련 원천 데이터는 `mavlink/raw_receiver.py`에서 `event_id`, `image_id`, `captured_at`, `lat/lon`, `confidence`, `image_name`, `image_path`까지 이미 만들어지고 있고, S3 업로드는 `backend/app/fire_detect_listener.py`에서 처리하고 있다. DB는 SQLAlchemy/Alembic이 이미 있으므로, `이벤트`와 `이미지 파일`을 분리한 2테이블 구조

## 추천 구조

- `fire_events`
- `fire_event_images`

이렇게 나누는 이유는 `event_id`와 `image_id`가 이미 분리돼 있고, 나중에 한 이벤트에 이미지가 여러 장 붙어도 자연스럽게 확장되기 때문이다.

```sql
CREATE TABLE fire_events (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  event_uid VARCHAR(64) NOT NULL UNIQUE,
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

## 핵심 포인트

- DB에는 `S3 URL`보다 `bucket + object_key`를 저장하는 것이 좋다.
- `presigned URL`은 만료되므로 DB에 저장하지 말고, 요청 시점에 생성하는 편이 안전하다.
- `image_path`는 컨테이너 경로라 배포나 재시작 시 바뀔 수 있으므로 참조용으로만 두고, 사용자 제공 기준은 S3 메타데이터로 잡는 것이 좋다.
- `raw_payload JSON`은 꼭 남기는 것이 좋다. 나중에 payload 필드가 늘어나도 마이그레이션 부담이 줄어든다.
- 조회가 많을 컬럼만 정규화해서 빼면 된다. 예시는 `captured_at`, `confidence`, `lat`, `lon`, `upload_status`다.

## 저장 흐름

1. Redis 이벤트 수신
2. `fire_events`를 `event_uid` 기준으로 upsert
3. `fire_event_images`를 `(fire_event_id, image_uid)` 기준으로 upsert하고 `upload_status='pending'`로 저장
4. S3 업로드 성공 시 `bucket`, `object_key`, `etag`, `uploaded_at`, `upload_status='uploaded'` 업데이트
5. 업로드 실패 시 `upload_status='failed'`, `upload_error` 저장

## 사용자 제공 방식

- 비공개 이미지면 API에서 DB 조회 후 presigned URL 생성
- 공개 이미지면 API에서 `bucket`과 `object_key`를 바탕으로 CDN 또는 public URL 생성
- 현재처럼 응답용으로 `payload["s3_image_url"]`를 붙이는 것은 괜찮지만, 영구 저장 기준값으로 삼는 것은 추천하지 않는다

## 결론

지금 단계에서는 `fire_events`와 `fire_event_images`의 2테이블 구조가 가장 균형이 좋다. 현재 payload 구조와도 잘 맞고, 나중에 조회 API, 업로드 재시도, 이미지 다건 처리까지 확장하기 쉽다.
