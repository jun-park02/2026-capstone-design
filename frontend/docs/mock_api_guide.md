# Mock API 연동 가이드

현재 프론트엔드 프로젝트는 개발 편의를 위해 **Mock 데이터(가짜 데이터)**와 **실제 백엔드 API**를 환경 변수로 쉽게 스위칭할 수 있도록 구성되어 있습니다.

---

## 1. 환경 변수 설정 (`.env`)

프로젝트 최상위 경로에 있는 `.env` 파일을 열어보면 다음과 같이 설정되어 있습니다.

```env
VITE_API_BASE_URL=http://localhost:8080/api
VITE_USE_MOCK_DATA=true
```

- `VITE_API_BASE_URL`: 실제 백엔드 서버의 주소입니다.
- `VITE_USE_MOCK_DATA`: `true`로 설정하면 프론트엔드 코드 내부에 정의된 Mock 데이터를 화면에 보여줍니다. `false`로 설정하면 `VITE_API_BASE_URL`로 실제 API 요청(HTTP GET, POST 등)을 보냅니다.

> **💡 참고:** `.env` 파일을 수정한 후에는 반드시 개발 서버(`npm run dev`)를 껐다가 다시 켜야 변경 사항이 적용됩니다.

---

## 2. 코드 내부 동작 원리

`src/api/config.ts` 파일에서 환경 변수를 읽어와 전역 플래그(`USE_MOCK_DATA`)로 내보냅니다.

```typescript
// src/api/config.ts
export const USE_MOCK_DATA = import.meta.env.VITE_USE_MOCK_DATA !== 'false';
```

각 페이지 컴포넌트(예: `Dashboard.tsx`, `MapPage.tsx` 등)에서는 이 플래그를 확인하여 다음과 같이 동작합니다.

```tsx
import { USE_MOCK_DATA, apiClient } from '../api/config';

const [data, setData] = useState(mockData); // 1. 초기값은 Mock 데이터로 설정

useEffect(() => {
  // 2. 만약 USE_MOCK_DATA가 false라면 실제 API를 호출하여 데이터를 덮어씌움
  if (!USE_MOCK_DATA) {
    apiClient.get('/dashboard/summary')
      .then(res => setData(res.data))
      .catch(err => console.error('Failed to fetch data:', err));
  }
}, []);
```

---

## 3. 백엔드 개발 시 필요 API 엔드포인트 목록

`VITE_USE_MOCK_DATA=false`로 설정했을 때 프론트엔드가 호출하는 API 엔드포인트는 다음과 같습니다. 백엔드 개발 시 이 규격에 맞춰 API를 만들어주시면 됩니다.

### 대시보드 (`/`)
- `GET /dashboard/summary` : 대시보드의 모든 통계 수치, 그래프 데이터, 대표 드론 위치 등을 객체 형태로 반환해야 합니다.

### 지도 (`/map`)
- `GET /drones` : 현재 운용 중인 드론들의 배열(위치, 배터리, 상태 등) 반환
- `GET /fires/active` : 현재 지도에 표시할 진행 중인 화재 배열 반환

### 알림 등록 (`/alerts`)
- `GET /alerts` : 등록된 이메일 목록 반환
- `POST /alerts` : 새 이메일 등록 (body: `{ email: string }`)
- `DELETE /alerts/:id` : 특정 이메일 삭제
- `PATCH /alerts/:id` : 특정 이메일 수신 상태 토글 (body: `{ active: boolean }`)

### 화재 세부 조회 (`/fires`)
- `GET /fires` : 전체 화재 이벤트 목록 반환
- `PATCH /fires/:id` : 화재 상태 변경 (오탐지/실제 화재 확정) (body: `{ status: string }`)
