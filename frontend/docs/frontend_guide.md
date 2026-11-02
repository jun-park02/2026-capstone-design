# 산불 탐지 시스템 프론트엔드 가이드

---

## 1. 백엔드 Base URL 변경 방법

현재 Base URL은 두 가지 방법으로 변경할 수 있습니다.

### 방법 A: UI에서 런타임에 변경하기 (가장 쉬운 방법)
1. 왼쪽 사이드바 맨 아래에 있는 **[설정]** 버튼을 클릭합니다.
2. 우측 상단에 나타나는 'API 설정' 모달 창에서 백엔드 주소(예: `http://192.168.0.10:8080/api`)를 입력하고 **[저장]**을 누릅니다.
3. 이 변경 사항은 `src/api/config.ts`의 `setApiBaseUrl` 함수를 통해 즉시 적용됩니다.

### 방법 B: 코드/환경변수 레벨에서 기본값 변경하기
개발 환경 자체의 기본 주소를 바꾸고 싶다면 아래 파일들을 수정하시면 됩니다.

1. **`src/api/config.ts` 파일 (4번째 줄)**
   ```typescript
   // 기존
   export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8080/api';
   // 변경
   export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '여러분의_실제_백엔드_주소';
   ```

2. **환경변수 파일 생성 (`.env`)**
   프로젝트 최상위 경로(`C:\Users\someff\Desktop\ewtwetew`)에 `.env` 파일을 만들고 아래 내용을 넣으면 코드를 수정하지 않아도 적용됩니다.
   ```env
   VITE_API_BASE_URL=http://여러분의_실제_백엔드_주소
   ```

---

## 2. 현재 보여지는 Mock 데이터의 위치

현재 화면에 보여지는 가짜(Mock) 데이터들은 백엔드가 연결되기 전 UI를 확인하기 위해 **각 페이지 컴포넌트 파일 상단**에 배열 형태로 하드코딩되어 있습니다. 

나중에 백엔드 API를 연결하실 때는 이 변수들을 지우고 `axios`나 `fetch`를 통해 받아온 상태(State)로 교체하시면 됩니다.

### 데이터 위치 안내

1. **대시보드 페이지 (`src/pages/Dashboard.tsx`)**
   - `yearlyData` (27번째 줄): 1년간 화재 감지 추이 그래프 데이터
   - `weeklyData` (34번째 줄): 일주일 화재 감지 그래프 데이터
   - `pieData` (41번째 줄): 오탐지 비율 원형 그래프 데이터
   - `dronePath` (47번째 줄): 미니 지도의 드론 이동 경로 좌표
   - `fireLocation` (53번째 줄): 미니 지도의 화재 발생 위치 좌표

2. **실시간 지도 페이지 (`src/pages/MapPage.tsx`)**
   - `mockDrones` (24번째 줄): 지도에 표시되는 드론 3대의 위치, 배터리, 상태 정보
   - `mockFires` (30번째 줄): 지도에 표시되는 화재 2건의 위치 및 상태 정보

3. **알림 등록 페이지 (`src/pages/AlertsPage.tsx`)**
   - `alerts` 상태 초기값 (14번째 줄): 기본으로 등록되어 있는 관리자 이메일 2개

4. **화재 세부 조회 페이지 (`src/pages/FiresPage.tsx`)**
   - `mockFires` (17번째 줄): 왼쪽 리스트에 뜨는 화재 이벤트 5건의 상세 정보(위치, 시간, 신뢰도 등)

백엔드 연동 작업을 시작하실 때 이 부분들을 실제 API 응답 데이터로 매핑해주시면 됩니다!
