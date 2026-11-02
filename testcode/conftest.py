import pytest
import io
from PIL import Image

# 이미지 생성 fixture
@pytest.fixture
def image_file():
    buf = io.BytesIO()
    image = Image.new("RGB", (100, 100), color="blue")
    image.save(buf, format="JPEG")
    # 읽기 포인터를 시작 위치로 이동
    buf.seek(0)
    return buf