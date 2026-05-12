import React, { useState, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/Card';
import { Flame, MapPin, Calendar, Clock, AlertTriangle, Search, Filter } from 'lucide-react';
import { USE_MOCK_DATA, apiClient } from '../api/config';

interface FireEvent {
  id: string;
  date: string;
  time: string;
  location: string;
  lat: number;
  lng: number;
  status: '진행중' | '확인됨' | '오탐지';
  droneId: string;
  confidence: number;
}

const mockFires: FireEvent[] = [
  { id: 'EVT-20260425-01', date: '2026-04-25', time: '14:32:45', location: '북악산 인근', lat: 37.5950, lng: 126.9800, status: '진행중', droneId: 'DRN-01', confidence: 98 },
  { id: 'EVT-20260425-02', date: '2026-04-25', time: '12:15:10', location: '인왕산 남측', lat: 37.5850, lng: 126.9700, status: '확인됨', droneId: 'DRN-02', confidence: 95 },
  { id: 'EVT-20260424-01', date: '2026-04-24', time: '09:45:22', location: '남산 타워 인근', lat: 37.5550, lng: 126.9850, status: '오탐지', droneId: 'DRN-01', confidence: 45 },
  { id: 'EVT-20260423-01', date: '2026-04-23', time: '16:20:05', location: '관악산 북측', lat: 37.5450, lng: 126.9500, status: '확인됨', droneId: 'DRN-03', confidence: 92 },
  { id: 'EVT-20260422-01', date: '2026-04-22', time: '11:10:30', location: '수락산 계곡', lat: 37.4500, lng: 126.9550, status: '확인됨', droneId: 'DRN-02', confidence: 88 },
];

export const FiresPage: React.FC = () => {
  const [searchTerm, setSearchTerm] = useState('');
  const [filterStatus, setFilterStatus] = useState<string>('전체');
  const [selectedFire, setSelectedFire] = useState<FireEvent | null>(null);
  const [fires, setFires] = useState<FireEvent[]>(
    USE_MOCK_DATA ? mockFires : []
  );

  useEffect(() => {
    if (!USE_MOCK_DATA) {
      apiClient.get('/fires')
        .then(res => setFires(res.data))
        .catch(err => console.error('Failed to fetch fires:', err));
    }
  }, []);

  const filteredFires = fires.filter(fire => {
    const matchesSearch = fire.id.toLowerCase().includes(searchTerm.toLowerCase()) || 
                          fire.location.toLowerCase().includes(searchTerm.toLowerCase());
    const matchesStatus = filterStatus === '전체' || fire.status === filterStatus;
    return matchesSearch && matchesStatus;
  });

  const getStatusBadge = (status: string) => {
    switch (status) {
      case '진행중':
        return <span className="inline-flex min-w-[3.5rem] items-center justify-center px-2.5 py-1 rounded-full bg-red-100 text-red-700 text-center text-xs font-medium">진행중</span>;
      case '확인됨':
        return <span className="inline-flex min-w-[3.5rem] items-center justify-center px-2.5 py-1 rounded-full bg-green-100 text-green-700 text-center text-xs font-medium">확인됨</span>;
      case '오탐지':
        return <span className="inline-flex min-w-[3.5rem] items-center justify-center px-2.5 py-1 rounded-full bg-slate-100 text-slate-600 text-center text-xs font-medium">오탐지</span>;
      default:
        return <span className="inline-flex min-w-[3.5rem] items-center justify-center px-2.5 py-1 rounded-full bg-slate-100 text-slate-700 text-center text-xs font-medium">{status}</span>;
    }
  };

  const handleUpdateStatus = async (id: string, newStatus: string) => {
    if (!USE_MOCK_DATA) {
      try {
        await apiClient.patch(`/fires/${id}`, { status: newStatus });
        setFires(fires.map(f => f.id === id ? { ...f, status: newStatus as any } : f));
        if (selectedFire?.id === id) {
          setSelectedFire({ ...selectedFire, status: newStatus as any });
        }
      } catch (error) {
        console.error('Failed to update fire status:', error);
        alert('상태 업데이트에 실패했습니다.');
      }
    } else {
      setFires(fires.map(f => f.id === id ? { ...f, status: newStatus as any } : f));
      if (selectedFire?.id === id) {
        setSelectedFire({ ...selectedFire, status: newStatus as any });
      }
    }
  };

  return (
    <div className="space-y-6 h-[calc(100vh-6rem)] flex flex-col">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold tracking-tight text-slate-900">화재 세부 조회</h2>
        <div className="flex gap-3">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" size={18} />
            <input
              type="text"
              placeholder="ID 또는 위치 검색..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="pl-10 pr-4 py-2 border border-slate-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none w-64"
            />
          </div>
          <div className="relative">
            <Filter className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" size={18} />
            <select
              value={filterStatus}
              onChange={(e) => setFilterStatus(e.target.value)}
              className="pl-10 pr-8 py-2 border border-slate-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none appearance-none bg-white"
            >
              <option value="전체">모든 상태</option>
              <option value="진행중">진행중</option>
              <option value="확인됨">확인됨</option>
              <option value="오탐지">오탐지</option>
            </select>
          </div>
        </div>
      </div>

      <div className="flex-1 flex gap-6 overflow-hidden">
        {/* 화재 목록 */}
        <Card className="w-1/2 flex flex-col overflow-hidden">
          <CardHeader className="bg-slate-50 border-b border-slate-100 py-4">
            <CardTitle className="text-lg font-semibold text-slate-800 flex justify-between items-center">
              <span>감지 이벤트 목록</span>
              <span className="text-sm font-normal text-slate-500 bg-white px-2 py-1 rounded border border-slate-200">
                총 {filteredFires.length}건
              </span>
            </CardTitle>
          </CardHeader>
          <CardContent className="flex-1 overflow-y-auto p-0">
            <ul className="divide-y divide-slate-100">
              {filteredFires.map(fire => (
                <li 
                  key={fire.id}
                  onClick={() => setSelectedFire(fire)}
                  className={`p-4 cursor-pointer hover:bg-slate-50 transition-colors ${selectedFire?.id === fire.id ? 'bg-blue-50 border-l-4 border-blue-500' : 'border-l-4 border-transparent'}`}
                >
                  <div className="flex justify-between items-start mb-2">
                    <div className="font-semibold text-slate-800">{fire.id}</div>
                    {getStatusBadge(fire.status)}
                  </div>
                  <div className="grid grid-cols-2 gap-y-2 text-sm text-slate-600 mt-3">
                    <div className="flex items-center gap-1.5"><MapPin size={14} className="text-slate-400" /> {fire.location}</div>
                    <div className="flex items-center gap-1.5"><Calendar size={14} className="text-slate-400" /> {fire.date}</div>
                    <div className="flex items-center gap-1.5"><Clock size={14} className="text-slate-400" /> {fire.time}</div>
                    <div className="flex items-center gap-1.5">
                      <AlertTriangle size={14} className={fire.confidence > 90 ? 'text-red-500' : 'text-orange-500'} /> 
                      신뢰도: {fire.confidence}%
                    </div>
                  </div>
                </li>
              ))}
              {filteredFires.length === 0 && (
                <div className="p-8 text-center text-slate-500">
                  <Search size={32} className="mx-auto mb-3 text-slate-300" />
                  <p>검색 결과가 없습니다.</p>
                </div>
              )}
            </ul>
          </CardContent>
        </Card>

        {/* 화재 세부 정보 */}
        <Card className="w-1/2 flex flex-col overflow-hidden bg-slate-50">
          {selectedFire ? (
            <>
              <CardHeader className="bg-white border-b border-slate-100 py-4">
                <CardTitle className="text-lg font-semibold text-slate-800 flex items-center gap-2">
                  <Flame className="text-red-500" size={20} />
                  이벤트 세부 정보
                </CardTitle>
              </CardHeader>
              <CardContent className="flex-1 overflow-y-auto p-6 space-y-6">
                <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-sm">
                  <div className="flex justify-between items-center mb-4 pb-4 border-b border-slate-100">
                    <h3 className="text-xl font-bold text-slate-900">{selectedFire.id}</h3>
                    {getStatusBadge(selectedFire.status)}
                  </div>
                  
                  <div className="grid grid-cols-2 gap-6">
                    <div className="space-y-4">
                      <div>
                        <div className="text-sm text-slate-500 mb-1">발생 일시</div>
                        <div className="font-medium text-slate-800 flex items-center gap-2">
                          <Calendar size={16} className="text-blue-500" /> {selectedFire.date} {selectedFire.time}
                        </div>
                      </div>
                      <div>
                        <div className="text-sm text-slate-500 mb-1">위치 정보</div>
                        <div className="font-medium text-slate-800 flex items-center gap-2">
                          <MapPin size={16} className="text-blue-500" /> {selectedFire.location}
                        </div>
                        <div className="text-sm text-slate-500 mt-1 ml-6">
                          ({selectedFire.lat.toFixed(4)}, {selectedFire.lng.toFixed(4)})
                        </div>
                      </div>
                    </div>
                    
                    <div className="space-y-4">
                      <div>
                        <div className="text-sm text-slate-500 mb-1">탐지 드론</div>
                        <div className="font-medium text-slate-800 flex items-center gap-2">
                          <div className="w-6 h-6 bg-slate-100 rounded-full flex items-center justify-center">🚁</div>
                          {selectedFire.droneId}
                        </div>
                      </div>
                      <div>
                        <div className="text-sm text-slate-500 mb-1">AI 신뢰도</div>
                        <div className="flex items-center gap-3">
                          <div className="flex-1 h-2 bg-slate-100 rounded-full overflow-hidden">
                            <div 
                              className={`h-full rounded-full ${selectedFire.confidence > 90 ? 'bg-red-500' : selectedFire.confidence > 70 ? 'bg-orange-500' : 'bg-yellow-500'}`} 
                              style={{ width: `${selectedFire.confidence}%` }}
                            ></div>
                          </div>
                          <span className="font-bold text-slate-800">{selectedFire.confidence}%</span>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>

                <div className="bg-slate-900 rounded-xl overflow-hidden aspect-video relative flex items-center justify-center shadow-inner border border-slate-800">
                  {/* Placeholder for Drone Camera Feed / Image */}
                  <div className="absolute top-4 left-4 bg-black/60 text-white px-3 py-1 rounded text-sm backdrop-blur-sm font-mono flex items-center gap-2">
                    <div className="w-2 h-2 bg-red-500 rounded-full animate-pulse"></div>
                    REC
                  </div>
                  <div className="absolute bottom-4 right-4 bg-black/60 text-white px-3 py-1 rounded text-xs backdrop-blur-sm font-mono">
                    {selectedFire.date} {selectedFire.time}
                  </div>
                  <div className="text-center text-slate-400">
                    <Flame size={48} className="mx-auto mb-2 opacity-50" />
                    <p>드론 카메라 캡처 이미지 / 영상 피드</p>
                    <p className="text-sm mt-1">백엔드 연동 시 표시됩니다.</p>
                  </div>
                </div>

                <div className="flex gap-3 justify-end">
                  <button 
                    onClick={() => handleUpdateStatus(selectedFire.id, '오탐지')}
                    className="px-4 py-2 bg-white border border-slate-300 rounded-lg text-slate-700 font-medium hover:bg-slate-50 transition-colors"
                  >
                    오탐지 처리
                  </button>
                  <button 
                    onClick={() => handleUpdateStatus(selectedFire.id, '확인됨')}
                    className="px-4 py-2 bg-red-600 text-white rounded-lg font-medium hover:bg-red-700 transition-colors shadow-sm"
                  >
                    실제 화재 확정
                  </button>
                </div>
              </CardContent>
            </>
          ) : (
            <div className="flex-1 flex flex-col items-center justify-center text-slate-400 p-8">
              <div className="w-20 h-20 bg-white rounded-full flex items-center justify-center mb-4 shadow-sm">
                <Search size={32} className="text-slate-300" />
              </div>
              <p className="text-lg font-medium text-slate-600">이벤트를 선택해주세요</p>
              <p className="text-sm mt-2 text-center max-w-xs">
                왼쪽 목록에서 화재 감지 이벤트를 선택하면 상세 정보와 드론 캡처 이미지를 확인할 수 있습니다.
              </p>
            </div>
          )}
        </Card>
      </div>
    </div>
  );
};
