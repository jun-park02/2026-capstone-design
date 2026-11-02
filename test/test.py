import cv2
import numpy as np

# 1. 이미지 읽기
img = cv2.imread('./heatmap-1781618085309_frame_001.png')


if len(img.shape) == 3 and img.shape[2] == 4:
    # 이미 알파 채널(4채널)이 있는 PNG라면 그대로 사용
    rgba = img.copy()
else:
    # 알파 채널이 없는 일반 PNG(또는 JPG)라면 알파 채널 추가
    rgba = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)

# 3. 검은색 픽셀 조건 (R, G, B가 모두 10 이하)
# 이미 투명한 부분은 건드리지 않고, 검은색 픽셀만 찾습니다.

black_pixels = np.where(
    (rgba[:, :, 2] <= 120)
)

# 4. 검은색 픽셀의 투명도(Alpha)를 0(완전 투명)으로 변경
print("aaaaaaaaaaaaaaaaaa", rgba[black_pixels])
rgba[black_pixels] = [0, 0, 0, 0]

# 5. 결과 저장
cv2.imwrite('output_transparent.png', rgba)