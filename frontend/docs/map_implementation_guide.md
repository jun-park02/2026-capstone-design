# 대시보드 미니 지도 구현 가이드

대시보드의 '오늘의 비행 경로 및 화재 탐지 위치' 미니 지도는 **React Leaflet** 라이브러리를 사용하여 구현되었습니다. 이 라이브러리는 오픈소스 지도 라이브러리인 Leaflet을 React 환경에서 쉽게 사용할 수 있게 해줍니다.

---

## 1. 사용된 라이브러리
- `leaflet`: 핵심 지도 렌더링 엔진
- `react-leaflet`: React용 Leaflet 래퍼(Wrapper) 컴포넌트들 (`MapContainer`, `TileLayer`, `Polyline`, `Marker` 등)

---

## 2. 컴포넌트 구조 및 렌더링 방식

`src/pages/Dashboard.tsx` 파일의 코드를 보면 다음과 같이 구성되어 있습니다.

```tsx
<MapContainer center={fireLocation} zoom={14} scrollWheelZoom={false} className="h-full w-full z-0">
  {/* 1. 배경 지도 타일 */}
  <TileLayer
    attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
    url="https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png"
  />
  
  {/* 2. 드론 비행 경로 (선) */}
  <Polyline positions={dronePath} color="#3b82f6" weight={3} dashArray="5, 10" />
  
  {/* 3. 화재 탐지 위치 (마커) */}
  <Marker position={fireLocation} icon={fireIcon}>
    <Popup>
      <div className="font-semibold text-red-600">화재 탐지 위치</div>
      <div className="text-sm text-slate-600">14:32 감지됨</div>
    </Popup>
  </Marker>
</MapContainer>
```

### 각 요소의 역할:
- **`MapContainer`**: 지도의 뼈대입니다. `center` 속성으로 지도의 초기 중심점(화재 위치)을 잡고, `zoom`으로 초기 확대 수준을 설정합니다.
- **`TileLayer`**: 지도의 배경 이미지(타일)를 불러옵니다. 현재 깔끔한 디자인을 위해 CartoDB의 `light_all` 테마(밝은 회색톤 지도)를 사용하고 있습니다.
- **`Polyline`**: 드론의 비행 경로를 그립니다. `positions`에 위도/경도 배열을 전달하면 그 점들을 이어 파란색 점선(`dashArray="5, 10"`)으로 표시합니다.
- **`Marker` & `Popup`**: 특정 좌표에 핀(아이콘)을 꽂습니다. 마커를 클릭하면 `Popup` 안의 내용(화재 탐지 시간 등)이 말풍선으로 나타납니다.

---

## 3. 데이터 구조 (어떻게 점을 찍는가?)

지도에 선을 그리고 점을 찍기 위해서는 **위도(Latitude)와 경도(Longitude)** 좌표 데이터가 필요합니다. 현재는 파일 상단에 다음과 같이 가짜(Mock) 데이터가 배열 형태로 정의되어 있습니다.

```typescript
// 드론이 이동한 경로 (위도, 경도 좌표들의 배열)
const dronePath: [number, number][] = [
  [37.5665, 126.9780], // 시작점
  [37.5700, 126.9820], // 중간점 1
  [37.5750, 126.9800], // 중간점 2
  [37.5800, 126.9850], // 끝점
];

// 화재가 감지된 단일 위치 (위도, 경도)
const fireLocation: [number, number] = [37.5750, 126.9800];
```

---

## 💡 향후 백엔드 연동 시 구현 방법

나중에 실제 드론 데이터를 받아와서 지도에 실시간으로 그리려면 다음과 같이 작업하시면 됩니다.

1. 백엔드에서 드론의 GPS 로그(위도, 경도 배열)와 화재 감지 이벤트의 좌표를 API로 받아옵니다.
2. 받아온 데이터를 React의 `useState`를 사용해 상태(State)로 저장합니다.
   ```typescript
   const [realDronePath, setRealDronePath] = useState<[number, number][]>([]);
   const [realFireLocation, setRealFireLocation] = useState<[number, number] | null>(null);
   ```
3. 저장된 상태 변수를 `Polyline`의 `positions`와 `Marker`의 `position` 속성에 각각 전달(Props)해 주면, 데이터가 업데이트될 때마다 지도의 선과 마커가 자동으로 다시 그려집니다.
