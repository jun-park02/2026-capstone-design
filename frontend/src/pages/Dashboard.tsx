import React, { useState, useEffect, useRef } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/Card';
import { LineChart, Line, BarChart, Bar, PieChart, Pie, Cell, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';
import { MapContainer, TileLayer, Marker, Popup, useMap } from 'react-leaflet';
import 'leaflet/dist/leaflet.css';
import L from 'leaflet';
import { USE_MOCK_DATA, apiClient } from '../api/config';

// Fix Leaflet marker icon issue
delete (L.Icon.Default.prototype as any)._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-icon-2x.png',
  iconUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-icon.png',
  shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-shadow.png',
});

const fireIcon = new L.Icon({
  iconUrl: 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-2x-red.png',
  shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-shadow.png',
  iconSize: [25, 41],
  iconAnchor: [12, 41],
  popupAnchor: [1, -34],
  shadowSize: [41, 41]
});

// Mock Data
const mockDashboardData = {
  status: '경고',
  activeSuspects: 12,
  resolvedToday: 45,
  activeFires: 3,
  avgDelay: 1.2,
  activeDrones: 8,
  errorCount: 3,
  avgBattery: 78,
  droneLocation: { lat: 37.5750, lng: 126.9800, alt: 120 },
  yearlyData: [
    { name: '1월', 감지: 12 }, { name: '2월', 감지: 19 }, { name: '3월', 감지: 30 },
    { name: '4월', 감지: 45 }, { name: '5월', 감지: 28 }, { name: '6월', 감지: 15 },
    { name: '7월', 감지: 10 }, { name: '8월', 감지: 8 }, { name: '9월', 감지: 22 },
    { name: '10월', 감지: 40 }, { name: '11월', 감지: 35 }, { name: '12월', 감지: 18 },
  ],
  weeklyData: [
    { name: '월', 전체: 5, 실제: 2 }, { name: '화', 전체: 8, 실제: 3 },
    { name: '수', 전체: 3, 실제: 1 }, { name: '목', 전체: 12, 실제: 8 },
    { name: '금', 전체: 7, 실제: 4 }, { name: '토', 전체: 15, 실제: 10 },
    { name: '일', 전체: 9, 실제: 5 },
  ],
  pieData: [
    { name: '실제 화재', value: 75 },
    { name: '오탐지', value: 25 },
  ],
  dronePath: [
    [37.5665, 126.9780],
    [37.5700, 126.9820],
    [37.5750, 126.9800],
    [37.5800, 126.9850],
  ] as [number, number][],
  fireLocations: [
    [37.5750, 126.9800],
    [37.5770, 126.9825],
  ] as [number, number][],
  monthTotal: 142,
  monthReal: 89
};

const COLORS = ['#ef4444', '#94a3b8'];
type Coordinate = [number, number];
const DEFAULT_MAP_CENTER: Coordinate = [37.5665, 126.9780];

const formatLocationValue = (value: number | string | null | undefined, suffix = '') => {
  if (value === null || value === undefined || value === '') {
    return '-';
  }

  return `${value}${suffix}`;
};

const MapAutoFit: React.FC<{ points: Coordinate[] }> = ({ points }) => {
  const map = useMap();
  const hasFitInitialView = useRef(false);

  useEffect(() => {
    if (hasFitInitialView.current || points.length === 0) {
      return;
    }

    hasFitInitialView.current = true;

    if (points.length === 1) {
      map.setView(points[0], 14);
      return;
    }

    map.fitBounds(L.latLngBounds(points), { padding: [24, 24], maxZoom: 14 });
  }, [map, points]);

  return null;
};

export const Dashboard: React.FC = () => {
  const [data, setData] = useState<typeof mockDashboardData | null>(
    USE_MOCK_DATA ? mockDashboardData : null
  );
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    if (!USE_MOCK_DATA) {
      const fetchDashboardData = async () => {
        try {
          const res = await apiClient.get('/dashboard/summary');
          setData(res.data);
          setLoadError(null);
        } catch (error) {
          console.error('Failed to fetch dashboard data:', error);
          setLoadError('실제 API 데이터를 불러오지 못했습니다.');
        }
      };

      fetchDashboardData();
      const interval = setInterval(fetchDashboardData, 10000); // 10초마다 갱신
      return () => clearInterval(interval);
    }
  }, []);

  if (!data) {
    return (
      <div className="flex h-[calc(100vh-6rem)] items-center justify-center text-sm text-slate-500">
        {loadError ?? '실제 API 데이터를 불러오는 중입니다...'}
      </div>
    );
  }

  const fireLocations = data.fireLocations ?? [];
  const droneLat = data.droneLocation?.lat;
  const droneLng = data.droneLocation?.lng;
  const hasDroneLocation = droneLat !== null && droneLat !== undefined && droneLng !== null && droneLng !== undefined;
  const mapCenter: Coordinate = fireLocations[0] ?? (hasDroneLocation ? [droneLat, droneLng] : DEFAULT_MAP_CENTER);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold tracking-tight text-slate-900">대시보드</h2>
        <div className="flex items-center gap-2 bg-white px-4 py-2 rounded-full shadow-sm border border-slate-200">
          <div className="w-3 h-3 bg-green-500 rounded-full animate-pulse"></div>
          <span className="text-sm font-medium text-slate-700">시스템 정상 작동 중</span>
        </div>
      </div>

      {/* 1. 현재 상태 관련 */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4">
        <Card className="bg-gradient-to-br from-blue-500 to-blue-600 text-white border-none">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-blue-100 flex items-center justify-between">
              현재 상태
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold">{data.status}</div>
            <p className="text-xs text-blue-200 mt-1">주의가 필요합니다</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-slate-500 flex items-center justify-between">
              진행 중인 화재 의심
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold text-slate-900">{data.activeSuspects}<span className="text-lg font-normal text-slate-500 ml-1">건</span></div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-slate-500 flex items-center justify-between">
              확인 완료 (오늘)
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold text-slate-900">{data.resolvedToday}<span className="text-lg font-normal text-slate-500 ml-1">건</span></div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-slate-500 flex items-center justify-between">
              진행 중인 실제 화재
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold text-slate-900">{data.activeFires}<span className="text-lg font-normal text-slate-500 ml-1">건</span></div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-slate-500 flex items-center justify-between">
              평균 표시 지연시간
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold text-slate-900">{data.avgDelay}<span className="text-lg font-normal text-slate-500 ml-1">초</span></div>
          </CardContent>
        </Card>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* 2. 드론 관련 */}
        <Card className="lg:col-span-1 flex flex-col">
          <CardHeader>
            <CardTitle className="text-lg font-semibold text-slate-800">드론 현황</CardTitle>
          </CardHeader>
          <CardContent className="flex-1 space-y-4">
            <div className="flex items-center justify-between p-3 bg-slate-50 rounded-lg">
              <div className="flex items-center gap-3">
                <span className="font-medium text-slate-700">Active 드론</span>
              </div>
              <span className="text-xl font-bold text-slate-900">{data.activeDrones} 대</span>
            </div>
            
            <div className="flex items-center justify-between p-3 bg-slate-50 rounded-lg">
              <div className="flex items-center gap-3">
                <span className="font-medium text-slate-700">에러/경고 메시지</span>
              </div>
              <span className="text-xl font-bold text-orange-600">{data.errorCount} 건</span>
            </div>

            <div className="flex items-center justify-between p-3 bg-slate-50 rounded-lg">
              <div className="flex items-center gap-3">
                <span className="font-medium text-slate-700">평균 배터리</span>
              </div>
              <div className="flex items-center gap-2">
                <div className="w-24 h-2 bg-slate-200 rounded-full overflow-hidden">
                  <div className="h-full bg-green-500" style={{ width: `${data.avgBattery}%` }}></div>
                </div>
                <span className="text-sm font-bold text-slate-900">{data.avgBattery}%</span>
              </div>
            </div>

            <div className="p-4 border border-slate-100 rounded-lg bg-white shadow-sm">
              <h4 className="text-sm font-semibold text-slate-500 mb-3 flex items-center gap-2">
                대표 드론 위치 (Drone-01)
              </h4>
              <div className="grid grid-cols-3 gap-2 text-center">
                <div className="bg-slate-50 p-2 rounded">
                  <div className="text-xs text-slate-500">위도</div>
                  <div className="font-medium text-slate-800">{formatLocationValue(data.droneLocation?.lat)}</div>
                </div>
                <div className="bg-slate-50 p-2 rounded">
                  <div className="text-xs text-slate-500">경도</div>
                  <div className="font-medium text-slate-800">{formatLocationValue(data.droneLocation?.lng)}</div>
                </div>
                <div className="bg-slate-50 p-2 rounded">
                  <div className="text-xs text-slate-500">고도</div>
                  <div className="font-medium text-slate-800">{formatLocationValue(data.droneLocation?.alt, 'm')}</div>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* 미니 지도 */}
        <Card className="lg:col-span-2 flex flex-col">
          <CardHeader>
            <CardTitle className="text-lg font-semibold text-slate-800">오늘의 화재 탐지 위치</CardTitle>
          </CardHeader>
          <CardContent className="flex-1 p-0 overflow-hidden rounded-b-xl min-h-[300px]">
            <MapContainer center={mapCenter} zoom={14} scrollWheelZoom={false} className="h-full w-full z-0">
              <MapAutoFit points={fireLocations} />
              <TileLayer
                attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
                url="https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png"
              />
              {fireLocations.map((fireLocation, index) => (
                <Marker key={`${fireLocation[0]}-${fireLocation[1]}-${index}`} position={fireLocation} icon={fireIcon}>
                  <Popup>
                    <div className="font-semibold text-red-600">화재 탐지 위치 #{index + 1}</div>
                    <div className="text-sm text-slate-600">
                      {fireLocation[0].toFixed(4)}, {fireLocation[1].toFixed(4)}
                    </div>
                  </Popup>
                </Marker>
              ))}
            </MapContainer>
          </CardContent>
        </Card>
      </div>

      {/* 3. 화재 관련 통계 */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card>
          <CardHeader>
            <CardTitle className="text-lg font-semibold text-slate-800">최근 1년간 화재 감지 추이</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="h-[300px] w-full mt-4">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={data.yearlyData}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
                  <XAxis dataKey="name" axisLine={false} tickLine={false} tick={{fill: '#64748b'}} />
                  <YAxis axisLine={false} tickLine={false} tick={{fill: '#64748b'}} />
                  <Tooltip 
                    contentStyle={{ borderRadius: '8px', border: 'none', boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.1)' }}
                  />
                  <Line type="monotone" dataKey="감지" stroke="#ef4444" strokeWidth={3} dot={{r: 4, strokeWidth: 2}} activeDot={{r: 6}} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-lg font-semibold text-slate-800">최근 일주일 화재 감지 (전체 vs 실제)</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="h-[300px] w-full mt-4">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={data.weeklyData}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
                  <XAxis dataKey="name" axisLine={false} tickLine={false} tick={{fill: '#64748b'}} />
                  <YAxis axisLine={false} tickLine={false} tick={{fill: '#64748b'}} />
                  <Tooltip 
                    cursor={{fill: '#f1f5f9'}}
                    contentStyle={{ borderRadius: '8px', border: 'none', boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.1)' }}
                  />
                  <Legend iconType="circle" wrapperStyle={{ paddingTop: '20px' }} />
                  <Bar dataKey="전체" fill="#94a3b8" radius={[4, 4, 0, 0]} barSize={20} />
                  <Bar dataKey="실제" fill="#ef4444" radius={[4, 4, 0, 0]} barSize={20} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle className="text-lg font-semibold text-slate-800">최근 한 달간 화재 감지 요약</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 gap-4 mt-2">
              <div className="bg-slate-50 p-6 rounded-xl border border-slate-100 flex flex-col items-center justify-center text-center">
                <div className="text-slate-500 mb-2 font-medium">전체 감지 건수</div>
                <div className="text-4xl font-bold text-slate-800">{data.monthTotal}<span className="text-lg font-normal text-slate-500 ml-1">건</span></div>
              </div>
              <div className="bg-red-50 p-6 rounded-xl border border-red-100 flex flex-col items-center justify-center text-center">
                <div className="text-red-500 mb-2 font-medium">실제 화재 이벤트</div>
                <div className="text-4xl font-bold text-red-600">{data.monthReal}<span className="text-lg font-normal text-red-400 ml-1">건</span></div>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card className="lg:col-span-1">
          <CardHeader>
            <CardTitle className="text-lg font-semibold text-slate-800">오탐지 비율 (최근 1달)</CardTitle>
          </CardHeader>
          <CardContent className="flex items-center justify-center">
            <div className="h-[200px] w-full">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={data.pieData}
                    cx="50%"
                    cy="50%"
                    innerRadius={60}
                    outerRadius={80}
                    paddingAngle={5}
                    dataKey="value"
                  >
                    {data.pieData.map((_entry, index) => (
                      <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip 
                    contentStyle={{ borderRadius: '8px', border: 'none', boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.1)' }}
                  />
                  <Legend verticalAlign="bottom" height={36} iconType="circle" />
                </PieChart>
              </ResponsiveContainer>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
};
