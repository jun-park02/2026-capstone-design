import logging
from datetime import datetime, UTC
import os
import json
from pathlib import Path
from logging.handlers import RotatingFileHandler
import sys

# 로그파일 회전 기능이 뭐야
# 파일은 10mib 단위로 교체하고 이전 파일 5개를 보관?

class JsonFormatter(logging.Formatter):
    # record는 로그 한 건의 정보를 담은 logging.LogRecord 객체
    def format(self, record):
        payload = {
            "@timestamp": datetime.fromtimestamp(
                # record.created는 로그가 생성된 시각을 특정 시점으로 부터 지난 초로 나타낸 숫자
                record.created, UTC # 이를 fromtimestamp 함수가 UTC 시간대의 datetime 객체로 변환
            ).isoformat(), # isoformat 함수는 datetime 객체를 ISO 8601 형식의 문자열로 변환

            "service": {
                "name": os.environ["LOG_SERVICE_NAME"], # 환경변수 넣어주기
            },

            "log": {
                "level": record.levelname,
            },

            "message": record.getMessage(),
        }

        # getattr은 무슨함수지. 3번째 매개변수는 뭐지
        # getattr()은 객체에서 지정한 이름의 속성 값을 가져오는 파이썬 내장함수. 세번째 매개변수는 해당 속성이 없을때 반환할 기본값
        # 세번째
        if getattr(record, "event_id", None) is not None:
            payload["event"] = {"id": str(record.event_id)}

        if getattr(record, "stage", None) is not None:
            payload["lables"] = {"stage": str(record.stage)}

        # 예외 정보를 담은 튜플
        if record.exc_info:
            payload["error"] = {
                "stack_trace": self.formatException(record.exc_info) # 예외 종류/메시지를 문자열로 만듦
            }

        return json.dumps(payload, ensure_ascii=False)


def get_logger():
    logger = logging.getLogger("capstone")

    # 이미 등록되어 있으면
    if logger.handlers:
        return logger

    service_name = os.environ["LOG_SERVICE_NAME"]
    log_dir = Path("/var/log/capstone") / service_name # /는 경로를 이어붙이는 연산자
    log_dir.mkdir(parents=True, exist_ok=True) # parents 매개변수?

    
    formatter = JsonFormatter()

    
    file_handler = RotatingFileHandler(
        log_dir / "app.jsonl", 
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8"
    )

    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    logger.setLevel(logging.INFO)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    logger.propagate = False

    return logger