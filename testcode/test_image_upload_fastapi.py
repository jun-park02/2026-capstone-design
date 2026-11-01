import requests
import json

IMAGE_UPLOAD_FASTAPI = "http://localhost:14551"

# 이게 구조가
# 이미지 수신 fastapi -> redis? -> fastapi
def test_upload_rgb_and_ir_images(
        image_file
):
    image_bytes = image_file.getvalue()
    
    # requests 라이브러리에서 files 파라미터로 multipart/form-data를 전송할때
    # (파일명, 파일 객체, MIME 타입) 순서의 튜플 구조로 받도록 정의
    files = {
        "RGB_image": ("test_image.jpg", image_bytes, "image/jpeg"),
        "IR_image": ("test_image2.jpg", image_bytes, "image/jpeg")
    }

    data = {
        "metadata": json.dumps({
            "timestamp": 1761976559.123,
            "gps": {
                "Latitude": "37.5985",
                "Longitude": "126.9380",
                "Altitude": "50.0"
            },
            "detection": {
                "objects": [
                    {
                        "class": "Fire",
                        "confidence": 0.5,
                        "bbox": [0, 0, 0, 0]
                    },
                ]
            }
        })
    }

    res = requests.post(
        IMAGE_UPLOAD_FASTAPI + "/fire-detections/upload", 
        files=files,
        data=data
    )

    assert res.status_code == 200, res.text
    print(res.json())
    assert res.json()["ok"] == True
    
# def test_reject_missing_rgb_image(): ...
# def test_reject_missing_ir_image(): ...
# def test_reject_empty_image(): ...
# def test_reject_oversized_image(): ...
# def test_reject_invalid_metadata_json(): ...
# def test_return_503_when_redis_publish_fails(): ...

# -------------- #





