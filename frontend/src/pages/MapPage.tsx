import React, { useState, useEffect } from 'react';
import { MapContainer, TileLayer, Marker, Popup, ZoomControl } from 'react-leaflet';
import { Card, CardContent } from '../components/ui/Card';
import { Navigation, Flame, Battery } from 'lucide-react';
import L from 'leaflet';
import { USE_MOCK_DATA, apiClient } from '../api/config';

// Icons
const droneIcon = new L.Icon({
  iconUrl: 'https://cdn-icons-png.flaticon.com/512/2855/2855018.png', // Example drone icon
  iconSize: [32, 32],
  iconAnchor: [16, 16],
  popupAnchor: [0, -16],
});

const fireIcon = new L.Icon({
  iconUrl: 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-2x-red.png',
  shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-shadow.png',
  iconSize: [25, 41],
  iconAnchor: [12, 41],
  popupAnchor: [1, -34],
  shadowSize: [41, 41]
});

const mockDrones = [
  { id: 'DRN-01', lat: 37.5665, lng: 126.9780, alt: 120, battery: 85, status: '정상' },
  { id: 'DRN-02', lat: 37.5700, lng: 126.9820, alt: 110, battery: 42, status: '경고' },
  { id: 'DRN-03', lat: 37.5600, lng: 126.9900, alt: 130, battery: 90, status: '정상' },
];

const mockFires = [
  { id: 'FIRE-01', lat: 37.5750, lng: 126.9800, time: '14:32', status: '진행중' },
  { id: 'FIRE-02', lat: 37.5550, lng: 126.9700, time: '12:15', status: '확인됨' },
];

export const MapPage: React.FC = () => {
  const [activeDrone, setActiveDrone] = useState<string | null>(null);
  const [drones, setDrones] = useState<typeof mockDrones>(
    USE_MOCK_DATA ? mockDrones : []
  );
  const [fires, setFires] = useState<typeof mockFires>(
    USE_MOCK_DATA ? mockFires : []
  );

  useEffect(() => {
    if (!USE_MOCK_DATA) {
      const fetchMapData = async () => {
        try {
          const [dronesRes, firesRes] = await Promise.all([
            apiClient.get('/drones'),
            apiClient.get('/fires/active')
          ]);
          setDrones(dronesRes.data);
          setFires(firesRes.data);
        } catch (error) {
          console.error('Failed to fetch map data:', error);
        }
      };

      fetchMapData();
      
      // 실시간 업데이트를 위한 폴링 (예: 5초마다)
      const interval = setInterval(fetchMapData, 5000);
      return () => clearInterval(interval);
    }
  }, []);

  return (
    <div className="h-[calc(100vh-6rem)] flex flex-col space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold tracking-tight text-slate-900">실시간 지도</h2>
        <div className="flex gap-2">
          <div className="flex items-center gap-2 bg-white px-3 py-1.5 rounded-md shadow-sm border border-slate-200 text-sm">
            <img src={droneIcon.options.iconUrl} alt="drone" className="w-4 h-4" />
            <span>드론 ({drones.length})</span>
          </div>
          <div className="flex items-center gap-2 bg-white px-3 py-1.5 rounded-md shadow-sm border border-slate-200 text-sm">
            <Flame size={16} className="text-red-500" />
            <span>화재 ({fires.length})</span>
          </div>
        </div>
      </div>

      <div className="flex-1 flex gap-4 relative">
        {/* 사이드 패널 (선택적 표시) */}
        <div className="w-80 flex flex-col gap-4 overflow-y-auto hidden md:flex">
          <Card className="border-slate-200 shadow-sm">
            <div className="p-4 border-b border-slate-100 bg-slate-50 rounded-t-xl">
              <h3 className="font-semibold text-slate-800 flex items-center gap-2">
                <Navigation size={18} className="text-blue-500" />
                운용 중인 드론
              </h3>
            </div>
            <CardContent className="p-0 divide-y divide-slate-100">
              {drones.map(drone => (
                <div 
                  key={drone.id} 
                  className={`p-4 hover:bg-slate-50 cursor-pointer transition-colors ${activeDrone === drone.id ? 'bg-blue-50 border-l-4 border-blue-500' : ''}`}
                  onClick={() => setActiveDrone(drone.id)}
                >
                  <div className="flex justify-between items-center mb-2">
                    <span className="font-semibold text-slate-800">{drone.id}</span>
                    <span className={`text-xs px-2 py-1 rounded-full font-medium ${drone.status === '정상' ? 'bg-green-100 text-green-700' : 'bg-orange-100 text-orange-700'}`}>
                      {drone.status}
                    </span>
                  </div>
                  <div className="grid grid-cols-2 gap-2 text-sm text-slate-600">
                    <div className="flex items-center gap-1"><Battery size={14} /> {drone.battery}%</div>
                    <div>고도: {drone.alt}m</div>
                  </div>
                </div>
              ))}
            </CardContent>
          </Card>
        </div>

        {/* 지도 영역 */}
        <Card className="flex-1 overflow-hidden shadow-sm border-slate-200 relative">
          <MapContainer 
            center={[37.5665, 126.9780]} 
            zoom={13} 
            className="h-full w-full z-0"
            zoomControl={false}
          >
            <TileLayer
              attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
              url="https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png"
            />
            <ZoomControl position="bottomright" />

            {/* Drones */}
            {drones.map(drone => (
              <Marker key={drone.id} position={[drone.lat, drone.lng]} icon={droneIcon}>
                <Popup className="rounded-lg">
                  <div className="p-1">
                    <h4 className="font-bold text-slate-800 border-b pb-1 mb-2">{drone.id}</h4>
                    <div className="space-y-1 text-sm">
                      <p><span className="text-slate-500">상태:</span> <span className={drone.status === '정상' ? 'text-green-600 font-medium' : 'text-orange-600 font-medium'}>{drone.status}</span></p>
                      <p><span className="text-slate-500">배터리:</span> {drone.battery}%</p>
                      <p><span className="text-slate-500">고도:</span> {drone.alt}m</p>
                      <p><span className="text-slate-500">위치:</span> {drone.lat.toFixed(4)}, {drone.lng.toFixed(4)}</p>
                    </div>
                  </div>
                </Popup>
              </Marker>
            ))}

            {/* Fires */}
            {fires.map(fire => (
              <Marker key={fire.id} position={[fire.lat, fire.lng]} icon={fireIcon}>
                <Popup>
                  <div className="p-1">
                    <h4 className="font-bold text-red-600 flex items-center gap-1 border-b pb-1 mb-2">
                      <Flame size={16} /> {fire.id}
                    </h4>
                    <div className="space-y-1 text-sm">
                      <p><span className="text-slate-500">상태:</span> <span className="font-medium">{fire.status}</span></p>
                      <p><span className="text-slate-500">감지 시간:</span> {fire.time}</p>
                      <p><span className="text-slate-500">위치:</span> {fire.lat.toFixed(4)}, {fire.lng.toFixed(4)}</p>
                    </div>
                  </div>
                </Popup>
              </Marker>
            ))}
          </MapContainer>
        </Card>
      </div>
    </div>
  );
};
