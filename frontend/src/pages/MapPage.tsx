import React, { useEffect, useMemo, useRef, useState } from 'react';
import { ImageOverlay, MapContainer, TileLayer, Marker, Popup, Polyline, ZoomControl, useMap } from 'react-leaflet';
import { Card, CardContent } from '../components/ui/Card';
import { Navigation, Flame, Battery, Layers, X } from 'lucide-react';
import L from 'leaflet';
import { API_BASE_URL, USE_MOCK_DATA, apiClient } from '../api/config';

const DRONE_FOCUS_ZOOM = 16;
const OVERVIEW_REFRESH_MS = 1000;
const BATTERY_SSE_REFRESH_SEC = 0.5;
const MAX_LIVE_PATH_POINTS = 500;
const DEFAULT_HEATMAP_OPACITY = 0.35;
const HEATMAP_FRAME_INTERVAL_MS = 1000;

const fireIcon = new L.Icon({
  iconUrl: 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-2x-red.png',
  shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-shadow.png',
  iconSize: [25, 41],
  iconAnchor: [12, 41],
  popupAnchor: [1, -34],
  shadowSize: [41, 41],
});

type Coordinate = [number, number];

interface Drone {
  id: string;
  lat: number;
  lng: number;
  alt: number | null;
  relativeAlt: number | null;
  heading: number | null;
  battery: number | null;
  va: number | null;
  voltage: number | null;
  vehicleStatus: string | null;
  armed: boolean | null;
  flightEnable: boolean | null;
}

interface FireMarker {
  id: string;
  lat: number;
  lng: number;
  time: string;
  status: '진행중' | '확인됨' | '오탐지';
}

type DronePaths = Record<string, Coordinate[]>;

interface BackendDronePoint {
  lat?: number | string | null;
  lon?: number | string | null;
  alt?: number | string | null;
  relative_alt?: number | string | null;
  va?: number | string | null;
  vehicle_status?: string | null;
  armed?: boolean | number | string | null;
  flight_enable?: boolean | number | string | null;
  heading?: number | string | null;
  position?: unknown;
}

interface BackendDronePath {
  drone_id?: string | number | null;
  system_id?: number | string | null;
  battery_remaining?: number | string | null;
  voltage_battery?: number | string | null;
  current_battery?: number | string | null;
  battery_soc?: number | string | null;
  battery_telemetry_at?: string | null;
  vehicle_status?: string | null;
  armed?: boolean | number | string | null;
  flight_enable?: boolean | number | string | null;
  path?: BackendDronePoint[];
  positions?: unknown[];
  latest?: BackendDronePoint | null;
}

interface BackendFireDetection {
  event_id: string;
  status?: string | null;
  lat?: number | string | null;
  lon?: number | string | null;
  captured_at?: string | null;
  received_at?: string | null;
  user_confirmation?: string | null;
}

interface MapOverviewResponse {
  drone_paths?: BackendDronePath[];
  fire_detections?: BackendFireDetection[];
}

interface DronePositionStreamItem {
  drone_id?: string | number | null;
  system_id?: string | number | null;
  lat?: number | string | null;
  lon?: number | string | null;
  alt?: number | string | null;
  relative_alt?: number | string | null;
  va?: number | string | null;
  vehicle_status?: string | null;
  armed?: boolean | number | string | null;
  flight_enable?: boolean | number | string | null;
  heading?: number | string | null;
  position?: unknown;
}

interface DroneBatteryStreamItem {
  drone_id?: string | number | null;
  system_id?: string | number | null;
  battery_remaining?: number | string | null;
  voltage_battery?: number | string | null;
}

interface HeatmapCorner {
  lat?: number | string | null;
  lon?: number | string | null;
  lng?: number | string | null;
  x?: number | string | null;
  y?: number | string | null;
}

interface HeatmapCoordinatesPayload {
  bottom_left?: HeatmapCorner | [number | string, number | string] | null;
  bottomLeft?: HeatmapCorner | [number | string, number | string] | null;
  top_right?: HeatmapCorner | [number | string, number | string] | null;
  topRight?: HeatmapCorner | [number | string, number | string] | null;
}

interface HeatmapFramePayload {
  frame_index?: number | string | null;
  image_url?: string | null;
  imageUrl?: string | null;
  prediction_minutes?: number | string | null;
  label?: string | null;
}

interface HeatmapOverlayPayload {
  ok?: boolean;
  image_url?: string | null;
  imageUrl?: string | null;
  frames?: HeatmapFramePayload[];
  coordinates?: HeatmapCoordinatesPayload | [unknown, unknown] | null;
  top_left?: HeatmapCorner | null;
  bottom_right?: HeatmapCorner | null;
  opacity?: number | string | null;
  heatmap_id?: string | number | null;
}

interface HeatmapFrameState {
  frameIndex: number;
  imageUrl: string;
  predictionMinutes: number;
  label: string;
}

interface HeatmapOverlayState {
  heatmapId: string | null;
  frames: HeatmapFrameState[];
  coordinates: [Coordinate, Coordinate];
  opacity: number;
}

interface StreamResponse<T> {
  ok?: boolean;
  items?: T[];
}

const mockDrones: Drone[] = [
  { id: 'DRN-01', lat: 37.5665, lng: 126.9780, alt: 120, relativeAlt: 38, heading: 35, battery: 85, va: 12.4, voltage: 49.48, vehicleStatus: 'MC_MODE_FLYING', armed: true, flightEnable: true },
  { id: 'DRN-02', lat: 37.5700, lng: 126.9820, alt: 110, relativeAlt: 31, heading: 125, battery: 42, va: 9.7, voltage: 47.92, vehicleStatus: 'ARMED', armed: true, flightEnable: false },
  { id: 'DRN-03', lat: 37.5600, lng: 126.9900, alt: 130, relativeAlt: 45, heading: 285, battery: 90, va: 10.9, voltage: 50.04, vehicleStatus: 'DISARMED', armed: false, flightEnable: false },
];

const mockFires: FireMarker[] = [
  { id: 'FIRE-01', lat: 37.5750, lng: 126.9800, time: '14:32', status: '진행중' },
  { id: 'FIRE-02', lat: 37.5550, lng: 126.9700, time: '12:15', status: '확인됨' },
];

const mockDronePaths: DronePaths = {
  'DRN-01': [
    [37.5628, 126.9705],
    [37.5641, 126.9728],
    [37.5654, 126.9754],
    [37.5665, 126.9780],
  ],
  'DRN-02': [
    [37.5758, 126.9885],
    [37.5739, 126.9861],
    [37.5718, 126.9840],
    [37.5700, 126.9820],
  ],
  'DRN-03': [
    [37.5526, 126.9948],
    [37.5550, 126.9935],
    [37.5576, 126.9917],
    [37.5600, 126.9900],
  ],
};

const DRONE_PATH_COLORS = ['#2563eb', '#0f766e', '#f97316', '#7c3aed', '#db2777'];

const getDronePathColor = (index: number) => DRONE_PATH_COLORS[index % DRONE_PATH_COLORS.length];

const apiUrl = (path: string) => `${API_BASE_URL.replace(/\/$/, '')}${path}`;

const normalizeHeading = (heading: number | null) => {
  if (heading === null) {
    return 0;
  }

  return ((heading % 360) + 360) % 360;
};

const formatHeading = (heading: number | null) => (
  heading === null ? '-' : `${Math.round(normalizeHeading(heading))}°`
);

const formatBattery = (battery: number | null) => (
  battery === null ? '-' : `${Math.round(battery)}%`
);

const statusTextFromVehicleStatus = (status: string | null) => {
  switch (status) {
    case 'DISARMED':
      return '시동꺼짐';
    case 'ARMED':
      return '시동중';
    case 'MC_MODE_FLYING':
      return '멀티콥터 비행중';
    case 'FW_MODE_FLYING':
      return '고정익 비행중';
    case 'TRANSITION':
      return '전방 천이 중';
    case 'BACKTRANSITION':
      return '역 천이중';
    case 'INVALID_STATE':
      return '유효하지 않는 상태';
    default:
      return null;
  }
};

const formatArmed = (armed: boolean | null, vehicleStatus: string | null = null) => {
  if (vehicleStatus === 'DISARMED') {
    return '시동꺼짐';
  }
  if (vehicleStatus && ['ARMED', 'MC_MODE_FLYING', 'FW_MODE_FLYING', 'TRANSITION', 'BACKTRANSITION'].includes(vehicleStatus)) {
    return '시동중';
  }
  if (vehicleStatus === 'INVALID_STATE') {
    return '유효하지 않는 상태';
  }
  if (armed === null) {
    return '시동 -';
  }

  return armed ? '시동중' : '시동꺼짐';
};

const formatFlightEnable = (flightEnable: boolean | null, vehicleStatus: string | null = null) => {
  const statusText = statusTextFromVehicleStatus(vehicleStatus);
  if (statusText) {
    if (vehicleStatus === 'DISARMED' || vehicleStatus === 'ARMED') {
      return '비행 아님';
    }
    return statusText;
  }
  if (flightEnable === null) {
    return '비행 -';
  }

  return flightEnable ? '비행중' : '비행 아님';
};

const conditionPillClass = (enabled: boolean | null) => {
  if (enabled === null) {
    return 'bg-slate-100 text-slate-500 border-slate-200';
  }

  return enabled
    ? 'bg-green-100 text-green-700 border-green-200'
    : 'bg-orange-100 text-orange-700 border-orange-200';
};

const conditionTextClass = (enabled: boolean | null) => {
  if (enabled === null) {
    return 'text-slate-500 font-medium';
  }

  return enabled ? 'text-green-600 font-medium' : 'text-orange-600 font-medium';
};

const formatMeters = (value: number | null) => (
  value === null ? '-' : `${Math.abs(value) >= 100 ? value.toFixed(0) : value.toFixed(1)}m`
);

const formatSpeed = (value: number | null) => (
  value === null ? '-' : `${value.toFixed(1)}m/s`
);

const formatVoltage = (value: number | null) => {
  if (value === null) {
    return '-';
  }

  const volts = Math.abs(value) > 1000 ? value / 1000 : value;
  return `${volts.toFixed(2)}V`;
};

const formatDroneLabel = (droneId: string) => `drone#${droneId}`;

const createDroneIcon = (heading: number | null) => {
  const rotation = normalizeHeading((heading ?? 0) + 90);

  return L.divIcon({
    className: 'drone-heading-marker',
    iconSize: [44, 44],
    iconAnchor: [22, 22],
    popupAnchor: [0, -22],
    html: `
      <div class="drone-heading-icon" style="--drone-heading: ${rotation}deg">
        <span class="drone-heading-chevron">^</span>
      </div>
    `,
  });
};

const toNumber = (value: unknown): number | null => {
  if (value === null || value === undefined || value === '') {
    return null;
  }

  const numberValue = Number(value);
  return Number.isFinite(numberValue) ? numberValue : null;
};

const toBoolean = (value: unknown): boolean | null => {
  if (value === null || value === undefined || value === '') {
    return null;
  }
  if (typeof value === 'boolean') {
    return value;
  }
  if (typeof value === 'number') {
    return value !== 0;
  }

  const normalized = String(value).trim().toLowerCase();
  if (['1', 'true', 'yes', 'on'].includes(normalized)) {
    return true;
  }
  if (['0', 'false', 'no', 'off'].includes(normalized)) {
    return false;
  }

  return null;
};

const normalizeVehicleStatus = (status: unknown): string | null => {
  if (status === null || status === undefined || status === '') {
    return null;
  }

  return String(status).trim().toUpperCase();
};

const flagsFromVehicleStatus = (status: string | null) => {
  switch (status) {
    case 'DISARMED':
      return { armed: false, flightEnable: false };
    case 'ARMED':
      return { armed: true, flightEnable: false };
    case 'MC_MODE_FLYING':
    case 'FW_MODE_FLYING':
    case 'TRANSITION':
    case 'BACKTRANSITION':
      return { armed: true, flightEnable: true };
    case 'INVALID_STATE':
      return { armed: false, flightEnable: false };
    case 'MC_STANDBY':
      return { armed: false, flightEnable: false };
    case 'MC_ARMED_STANDBY':
      return { armed: true, flightEnable: false };
    case 'MC_FLYING':
      return { armed: true, flightEnable: true };
    case 'MC_INVALID_STATE':
      return { armed: false, flightEnable: true };
    default:
      return { armed: null, flightEnable: null };
  }
};

const toCoordinate = (value: unknown): Coordinate | null => {
  if (!Array.isArray(value) || value.length < 2) {
    return null;
  }

  const lat = toNumber(value[0]);
  const lng = toNumber(value[1]);
  return lat === null || lng === null ? null : [lat, lng];
};

const coordinateFromPoint = (point?: BackendDronePoint | null): Coordinate | null => {
  if (!point) {
    return null;
  }

  return toCoordinate(point.position) ?? (() => {
    const lat = toNumber(point.lat);
    const lng = toNumber(point.lon);
    return lat === null || lng === null ? null : [lat, lng];
  })();
};

const buildDronePath = (dronePath: BackendDronePath): Coordinate[] => {
  const directPositions = (dronePath.positions ?? [])
    .map(toCoordinate)
    .filter((point): point is Coordinate => point !== null);

  if (directPositions.length > 0) {
    return directPositions;
  }

  return (dronePath.path ?? [])
    .map(coordinateFromPoint)
    .filter((point): point is Coordinate => point !== null);
};

const droneIdFromStreamItem = (item: DronePositionStreamItem | DroneBatteryStreamItem) => {
  const id = item.drone_id ?? item.system_id;
  return id === null || id === undefined || id === '' ? null : String(id);
};

const coordinateFromStreamItem = (item: DronePositionStreamItem): Coordinate | null => (
  toCoordinate(item.position) ?? (() => {
    const lat = toNumber(item.lat);
    const lng = toNumber(item.lon);
    return lat === null || lng === null ? null : [lat, lng];
  })()
);

const coordinateFromHeatmapPoint = (
  point?: HeatmapCorner | [number | string, number | string] | null,
): Coordinate | null => {
  if (!point) {
    return null;
  }

  if (Array.isArray(point)) {
    const lng = toNumber(point[0]);
    const lat = toNumber(point[1]);
    return lat === null || lng === null ? null : [lat, lng];
  }

  const lat = toNumber(point.lat ?? point.y);
  const lng = toNumber(point.lon ?? point.lng ?? point.x);
  return lat === null || lng === null ? null : [lat, lng];
};

const coordinatesFromHeatmapPayload = (payload: HeatmapOverlayPayload): [Coordinate, Coordinate] | null => {
  const coordinates = payload.coordinates;
  let bottomLeft: Coordinate | null = null;
  let topRight: Coordinate | null = null;

  if (Array.isArray(coordinates) && coordinates.length >= 2) {
    bottomLeft = toCoordinate(coordinates[0]);
    topRight = toCoordinate(coordinates[1]);
  } else if (coordinates && typeof coordinates === 'object') {
    const coordinateObject = coordinates as HeatmapCoordinatesPayload;
    bottomLeft = coordinateFromHeatmapPoint(coordinateObject.bottom_left ?? coordinateObject.bottomLeft);
    topRight = coordinateFromHeatmapPoint(coordinateObject.top_right ?? coordinateObject.topRight);
  }

  if (!bottomLeft || !topRight) {
    const topLeft = coordinateFromHeatmapPoint(payload.top_left);
    const bottomRight = coordinateFromHeatmapPoint(payload.bottom_right);
    if (topLeft && bottomRight) {
      const north = Math.max(topLeft[0], bottomRight[0]);
      const south = Math.min(topLeft[0], bottomRight[0]);
      const east = Math.max(topLeft[1], bottomRight[1]);
      const west = Math.min(topLeft[1], bottomRight[1]);
      return [[south, west], [north, east]];
    }
    return null;
  }

  const north = Math.max(bottomLeft[0], topRight[0]);
  const south = Math.min(bottomLeft[0], topRight[0]);
  const east = Math.max(bottomLeft[1], topRight[1]);
  const west = Math.min(bottomLeft[1], topRight[1]);
  return [[south, west], [north, east]];
};

const clampOpacity = (value: unknown) => {
  const opacity = toNumber(value);
  if (opacity === null) {
    return DEFAULT_HEATMAP_OPACITY;
  }

  return Math.min(1, Math.max(0, opacity));
};

const resolveHeatmapImageUrl = (imageUrl: string) => {
  if (/^https?:\/\//i.test(imageUrl) || imageUrl.startsWith('data:')) {
    return imageUrl;
  }

  return apiUrl(imageUrl.startsWith('/') ? imageUrl : `/${imageUrl}`);
};

const normalizeHeatmapFrame = (
  frame: HeatmapFramePayload,
  fallbackIndex: number,
): HeatmapFrameState | null => {
  const imageUrl = frame.image_url ?? frame.imageUrl;
  if (!imageUrl) {
    return null;
  }

  const frameIndex = toNumber(frame.frame_index) ?? fallbackIndex;
  const predictionMinutes = toNumber(frame.prediction_minutes) ?? (frameIndex + 1) * 10;
  return {
    frameIndex,
    imageUrl: resolveHeatmapImageUrl(imageUrl),
    predictionMinutes,
    label: frame.label ?? `${predictionMinutes}분 뒤 확산 예측 히트맵`,
  };
};

const normalizeHeatmapOverlay = (payload: HeatmapOverlayPayload): HeatmapOverlayState | null => {
  if (payload.ok === false) {
    return null;
  }

  const coordinates = coordinatesFromHeatmapPayload(payload);
  if (!coordinates) {
    return null;
  }

  const frames = (payload.frames ?? [])
    .map(normalizeHeatmapFrame)
    .filter((frame): frame is HeatmapFrameState => frame !== null)
    .sort((a, b) => a.frameIndex - b.frameIndex);

  if (frames.length === 0 && (payload.image_url || payload.imageUrl)) {
    const singleFrame = normalizeHeatmapFrame(
      {
        frame_index: 0,
        image_url: payload.image_url,
        imageUrl: payload.imageUrl,
      },
      0,
    );
    if (singleFrame) {
      frames.push(singleFrame);
    }
  }

  if (frames.length === 0) {
    return null;
  }

  return {
    heatmapId: payload.heatmap_id === null || payload.heatmap_id === undefined ? null : String(payload.heatmap_id),
    frames,
    coordinates,
    opacity: clampOpacity(payload.opacity),
  };
};

const appendPathPoint = (path: Coordinate[] | undefined, point: Coordinate) => {
  const nextPath = path ? [...path] : [];
  const lastPoint = nextPath[nextPath.length - 1];
  if (!lastPoint || lastPoint[0] !== point[0] || lastPoint[1] !== point[1]) {
    nextPath.push(point);
  }
  return nextPath.slice(-MAX_LIVE_PATH_POINTS);
};

const formatTime = (value?: string | null) => {
  if (!value) {
    return '-';
  }

  const timePart = value.includes('T') ? value.split('T')[1] : value.split(' ')[1];
  return timePart ? timePart.slice(0, 5) : value;
};

const toFireStatus = (status?: string | null, confirmation?: string | null): FireMarker['status'] => {
  if (confirmation === 'Y' || status === 'confirmed' || status === 'fire_confirmed') {
    return '확인됨';
  }
  if (confirmation === 'N' || status === 'rejected' || status === 'reviewed') {
    return '오탐지';
  }
  return '진행중';
};

const transformOverview = (overview: MapOverviewResponse) => {
  const nextDronePaths: DronePaths = {};
  const nextDrones = (overview.drone_paths ?? [])
    .map((dronePath, index): Drone | null => {
      const path = buildDronePath(dronePath);
      const latestPoint = coordinateFromPoint(dronePath.latest) ?? path[path.length - 1];
      if (!latestPoint) {
        return null;
      }

      const id = String(dronePath.drone_id ?? dronePath.system_id ?? `DRN-${index + 1}`);
      const latestAlt = toNumber(dronePath.latest?.alt);
      const latestRelativeAlt = toNumber(dronePath.latest?.relative_alt);
      const latestVa = toNumber(dronePath.latest?.va);
      const latestHeading = toNumber(dronePath.latest?.heading);
      const latestBattery = toNumber(dronePath.battery_remaining);
      const latestVoltage = toNumber(dronePath.voltage_battery);
      const vehicleStatus = normalizeVehicleStatus(dronePath.vehicle_status ?? dronePath.latest?.vehicle_status);
      const statusFlags = flagsFromVehicleStatus(vehicleStatus);
      const armed = toBoolean(dronePath.armed ?? dronePath.latest?.armed) ?? statusFlags.armed;
      const flightEnable = toBoolean(dronePath.flight_enable ?? dronePath.latest?.flight_enable) ?? statusFlags.flightEnable;
      nextDronePaths[id] = path.length > 0 ? path : [latestPoint];

      return {
        id,
        lat: latestPoint[0],
        lng: latestPoint[1],
        alt: latestAlt,
        relativeAlt: latestRelativeAlt,
        heading: latestHeading,
        battery: latestBattery,
        va: latestVa,
        voltage: latestVoltage,
        vehicleStatus,
        armed,
        flightEnable,
      };
    })
    .filter((drone): drone is Drone => drone !== null);

  const nextFires = (overview.fire_detections ?? [])
    .map((fire) => {
      const lat = toNumber(fire.lat);
      const lng = toNumber(fire.lon);
      if (lat === null || lng === null) {
        return null;
      }

      return {
        id: fire.event_id,
        lat,
        lng,
        time: formatTime(fire.captured_at ?? fire.received_at),
        status: toFireStatus(fire.status, fire.user_confirmation),
      };
    })
    .filter((fire): fire is FireMarker => fire !== null);

  return { drones: nextDrones, dronePaths: nextDronePaths, fires: nextFires };
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

    map.fitBounds(L.latLngBounds(points), { padding: [32, 32], maxZoom: 14 });
  }, [map, points]);

  return null;
};

const DroneFocus: React.FC<{ drone: Drone | null }> = ({ drone }) => {
  const map = useMap();

  useEffect(() => {
    if (!drone) {
      return;
    }

    map.flyTo([drone.lat, drone.lng], DRONE_FOCUS_ZOOM, {
      animate: true,
      duration: 0.8,
    });
  }, [map, drone]);

  return null;
};

const HeatmapLabelOverlay: React.FC<{
  coordinates: [Coordinate, Coordinate];
  label: string;
}> = ({ coordinates, label }) => {
  const map = useMap();
  const [position, setPosition] = useState<{ left: number; top: number } | null>(null);

  useEffect(() => {
    const updatePosition = () => {
      const bounds = L.latLngBounds(coordinates);
      const bottomRight = map.latLngToContainerPoint(bounds.getSouthEast());
      const mapSize = map.getSize();

      setPosition({
        left: Math.min(Math.max(bottomRight.x, 16), mapSize.x - 16),
        top: Math.min(Math.max(bottomRight.y, 16), mapSize.y - 16),
      });
    };

    updatePosition();
    map.on('move zoom resize', updatePosition);

    return () => {
      map.off('move zoom resize', updatePosition);
    };
  }, [coordinates, map]);

  if (!position) {
    return null;
  }

  return (
    <div
      className="pointer-events-none absolute z-[500] -translate-x-full -translate-y-full rounded-md border border-slate-200 bg-white/95 px-3 py-2 text-sm font-medium text-slate-800 shadow-sm"
      style={{
        left: position.left,
        top: position.top,
        marginLeft: -8,
        marginTop: -8,
      }}
    >
      {label}
    </div>
  );
};

export const MapPage: React.FC = () => {
  const [activeDrone, setActiveDrone] = useState<string | null>(null);
  const [drones, setDrones] = useState<Drone[]>(USE_MOCK_DATA ? mockDrones : []);
  const [dronePaths, setDronePaths] = useState<DronePaths>(USE_MOCK_DATA ? mockDronePaths : {});
  const [fires, setFires] = useState<FireMarker[]>(USE_MOCK_DATA ? mockFires : []);
  const [heatmapOverlay, setHeatmapOverlay] = useState<HeatmapOverlayState | null>(null);
  const [heatmapFrameIndex, setHeatmapFrameIndex] = useState(0);
  const [heatmapReplayRequest, setHeatmapReplayRequest] = useState(0);
  const [heatmapReplayLatest, setHeatmapReplayLatest] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    if (USE_MOCK_DATA) {
      return;
    }

    let isMounted = true;

    const syncMapOverview = async () => {
      try {
        const res = await apiClient.get<MapOverviewResponse>('/map/overview');
        const nextData = transformOverview(res.data);
        if (!isMounted) {
          return;
        }
        setDrones(nextData.drones);
        setDronePaths(nextData.dronePaths);
        setFires(nextData.fires);
        setLoadError(null);
      } catch (error) {
        console.error('Failed to fetch map overview:', error);
        if (isMounted) {
          setLoadError('지도 데이터를 불러오지 못했습니다.');
        }
      }
    };

    const positionSource = new EventSource(apiUrl('/drones/position/stream'));
    const batterySource = new EventSource(apiUrl(`/drones/battery/stream?interval_sec=${BATTERY_SSE_REFRESH_SEC}`));

    positionSource.addEventListener('position', (event) => {
      try {
        const payload = JSON.parse(event.data) as StreamResponse<DronePositionStreamItem>;
        const items = payload.items ?? [];

        setDrones((currentDrones) => {
          const dronesById = new Map(currentDrones.map((drone) => [drone.id, drone]));

          for (const item of items) {
            const id = droneIdFromStreamItem(item);
            const coordinate = coordinateFromStreamItem(item);
            if (!id || !coordinate) {
              continue;
            }

            const existingDrone = dronesById.get(id);
            const vehicleStatus = normalizeVehicleStatus(item.vehicle_status) ?? existingDrone?.vehicleStatus ?? null;
            const statusFlags = flagsFromVehicleStatus(vehicleStatus);
            dronesById.set(id, {
              id,
              lat: coordinate[0],
              lng: coordinate[1],
              alt: toNumber(item.alt) ?? existingDrone?.alt ?? null,
              relativeAlt: toNumber(item.relative_alt) ?? existingDrone?.relativeAlt ?? null,
              heading: toNumber(item.heading) ?? existingDrone?.heading ?? null,
              battery: existingDrone?.battery ?? null,
              va: toNumber(item.va) ?? existingDrone?.va ?? null,
              voltage: existingDrone?.voltage ?? null,
              vehicleStatus,
              armed: toBoolean(item.armed) ?? statusFlags.armed ?? existingDrone?.armed ?? null,
              flightEnable: toBoolean(item.flight_enable) ?? statusFlags.flightEnable ?? existingDrone?.flightEnable ?? null,
            });
          }

          return Array.from(dronesById.values());
        });

        setDronePaths((currentPaths) => {
          const nextPaths = { ...currentPaths };

          for (const item of items) {
            const id = droneIdFromStreamItem(item);
            const coordinate = coordinateFromStreamItem(item);
            if (!id || !coordinate) {
              continue;
            }

            nextPaths[id] = appendPathPoint(nextPaths[id], coordinate);
          }

          return nextPaths;
        });
      } catch (error) {
        console.error('Failed to parse drone position SSE:', error);
      }
    });

    batterySource.addEventListener('battery', (event) => {
      try {
        const payload = JSON.parse(event.data) as StreamResponse<DroneBatteryStreamItem>;
        const items = payload.items ?? [];

        setDrones((currentDrones) => {
          const batteriesById = new Map<string, { battery: number | null; voltage: number | null }>();
          for (const item of items) {
            const id = droneIdFromStreamItem(item);
            if (!id) {
              continue;
            }
            batteriesById.set(id, {
              battery: toNumber(item.battery_remaining),
              voltage: toNumber(item.voltage_battery),
            });
          }

          if (batteriesById.size === 0) {
            return currentDrones;
          }

          return currentDrones.map((drone) => {
            const batteryUpdate = batteriesById.get(drone.id);
            if (!batteryUpdate) {
              return drone;
            }

            return {
              ...drone,
              battery: batteryUpdate.battery,
              voltage: batteryUpdate.voltage ?? drone.voltage,
            };
          });
        });
      } catch (error) {
        console.error('Failed to parse drone battery SSE:', error);
      }
    });

    const handleStreamError = () => {
      if (isMounted) {
        setLoadError('실시간 드론 데이터를 연결하지 못했습니다.');
      }
    };

    positionSource.onerror = handleStreamError;
    batterySource.onerror = handleStreamError;

    syncMapOverview();
    const interval = setInterval(syncMapOverview, OVERVIEW_REFRESH_MS);

    return () => {
      isMounted = false;
      clearInterval(interval);
      positionSource.close();
      batterySource.close();
    };
  }, []);

  useEffect(() => {
    if (USE_MOCK_DATA) {
      return;
    }

    let isMounted = true;
    const heatmapSource = new EventSource(
      apiUrl(
        `/heatmaps/stream?replay_latest=${heatmapReplayLatest ? 'true' : 'false'}&request_id=${heatmapReplayRequest}`,
      ),
    );

    const handleHeatmapEvent = (event: MessageEvent) => {
      try {
        const payload = JSON.parse(event.data) as HeatmapOverlayPayload;
        const nextOverlay = normalizeHeatmapOverlay(payload);
        if (nextOverlay && isMounted) {
          setHeatmapOverlay(nextOverlay);
          setHeatmapFrameIndex(0);
        }
      } catch (error) {
        console.error('Failed to parse heatmap SSE:', error);
      }
    };

    heatmapSource.addEventListener('heatmap', handleHeatmapEvent);
    heatmapSource.onmessage = handleHeatmapEvent;
    heatmapSource.onerror = () => {
      console.warn('Heatmap SSE disconnected.');
    };

    return () => {
      isMounted = false;
      heatmapSource.close();
    };
  }, [heatmapReplayLatest, heatmapReplayRequest]);

  const mapFitPoints = useMemo(() => {
    const pathPoints = Object.values(dronePaths).reduce<Coordinate[]>(
      (points, path) => [...points, ...path],
      [],
    );
    const firePoints = fires.map((fire) => [fire.lat, fire.lng] as Coordinate);
    const heatmapPoints = heatmapOverlay ? heatmapOverlay.coordinates : [];
    return [...pathPoints, ...firePoints, ...heatmapPoints];
  }, [dronePaths, fires, heatmapOverlay]);
  useEffect(() => {
    if (!heatmapOverlay || heatmapOverlay.frames.length <= 1) {
      return;
    }

    const interval = window.setInterval(() => {
      setHeatmapFrameIndex((currentFrameIndex) => (
        (currentFrameIndex + 1) % heatmapOverlay.frames.length
      ));
    }, HEATMAP_FRAME_INTERVAL_MS);

    return () => window.clearInterval(interval);
  }, [heatmapOverlay?.heatmapId, heatmapOverlay?.frames.length]);

  const currentHeatmapFrame = useMemo(() => {
    if (!heatmapOverlay || heatmapOverlay.frames.length === 0) {
      return null;
    }

    return heatmapOverlay.frames[heatmapFrameIndex % heatmapOverlay.frames.length];
  }, [heatmapFrameIndex, heatmapOverlay]);
  const selectedDrone = useMemo(
    () => drones.find((drone) => drone.id === activeDrone) ?? null,
    [activeDrone, drones],
  );
  const toggleActiveDrone = (droneId: string) => {
    setActiveDrone((currentDroneId) => (currentDroneId === droneId ? null : droneId));
  };
  const loadLatestHeatmap = () => {
    setHeatmapReplayLatest(true);
    setHeatmapReplayRequest((requestId) => requestId + 1);
  };
  const clearHeatmap = () => {
    setHeatmapOverlay(null);
    setHeatmapFrameIndex(0);
    setHeatmapReplayLatest(false);
    setHeatmapReplayRequest((requestId) => requestId + 1);
  };

  return (
    <div className="h-[calc(100vh-6rem)] flex flex-col space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold tracking-tight text-slate-900">실시간 지도</h2>
        <div className="flex items-center gap-2">
          {loadError && <span className="text-sm text-red-600">{loadError}</span>}
          <div className="flex items-center gap-2 bg-white px-3 py-1.5 rounded-md shadow-sm border border-slate-200 text-sm">
            <span className="drone-heading-count-icon" aria-hidden="true">^</span>
            <span>드론 ({drones.length})</span>
          </div>
          <div className="flex items-center gap-2 bg-white px-3 py-1.5 rounded-md shadow-sm border border-slate-200 text-sm">
            <Flame size={16} className="text-red-500" />
            <span>화재 ({fires.length})</span>
          </div>
          <button
            type="button"
            onClick={loadLatestHeatmap}
            className="flex items-center gap-2 bg-white px-3 py-1.5 rounded-md shadow-sm border border-slate-200 text-sm hover:bg-slate-50 transition-colors"
            title="최신 히트맵 불러오기"
          >
            <Layers size={16} className="text-amber-500" />
            <span>최신 히트맵</span>
          </button>
          {heatmapOverlay && (
            <button
              type="button"
              onClick={clearHeatmap}
              className="flex items-center gap-2 bg-white px-3 py-1.5 rounded-md shadow-sm border border-slate-200 text-sm hover:bg-slate-50 transition-colors"
              title="새 히트맵이 들어올 때까지 현재 히트맵 받지 않기"
            >
              <X size={16} className="text-slate-500" />
              <span>새 히트맵까지 중지</span>
            </button>
          )}
        </div>
      </div>

      <div className="flex-1 flex gap-4 relative">
        <div className="w-96 flex-col gap-4 overflow-y-auto hidden md:flex">
          <Card className="border-slate-200 shadow-sm">
            <div className="p-5 border-b border-slate-100 bg-slate-50 rounded-t-xl">
              <h3 className="font-semibold text-slate-800 flex items-center gap-2">
                <Navigation size={18} className="text-blue-500" />
                운용 중인 드론
              </h3>
            </div>
            <CardContent className="p-0 divide-y divide-slate-100">
              {drones.map((drone) => (
                <div
                  key={drone.id}
                  className={`p-5 hover:bg-slate-50 cursor-pointer transition-colors ${activeDrone === drone.id ? 'bg-blue-50 border-l-4 border-blue-500' : ''}`}
                  onClick={() => toggleActiveDrone(drone.id)}
                >
                  <div className="flex justify-between items-center mb-3">
                    <span className="text-base font-semibold text-slate-800">{formatDroneLabel(drone.id)}</span>
                  </div>
                  <div className="grid grid-cols-2 gap-x-4 gap-y-2.5 text-sm text-slate-600">
                    <div className="col-span-2 flex flex-wrap gap-2">
                      <span className={`rounded-full border px-2.5 py-1 text-xs font-medium ${conditionPillClass(drone.armed)}`}>
                        {formatArmed(drone.armed, drone.vehicleStatus)}
                      </span>
                      <span className={`rounded-full border px-2.5 py-1 text-xs font-medium ${conditionPillClass(drone.flightEnable)}`}>
                        {formatFlightEnable(drone.flightEnable, drone.vehicleStatus)}
                      </span>
                    </div>
                    <div className="flex items-center gap-1.5 font-medium text-slate-700">
                      <Battery size={14} />
                      {formatBattery(drone.battery)}
                    </div>
                    <div>전압: {formatVoltage(drone.voltage)}</div>
                    <div>고도: {formatMeters(drone.alt)}</div>
                    <div>상대고도: {formatMeters(drone.relativeAlt)}</div>
                    <div>속력: {formatSpeed(drone.va)}</div>
                    <div>헤딩: {formatHeading(drone.heading)}</div>
                  </div>
                </div>
              ))}
            </CardContent>
          </Card>
        </div>

        <Card className="flex-1 overflow-hidden shadow-sm border-slate-200 relative">
          <MapContainer
            center={[37.5665, 126.9780]}
            zoom={13}
            className="h-full w-full z-0"
            zoomControl={false}
          >
            <MapAutoFit points={mapFitPoints} />
            <DroneFocus drone={selectedDrone} />
            <TileLayer
              attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
              url="https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png"
            />
            {heatmapOverlay && currentHeatmapFrame && (
              <ImageOverlay
                url={currentHeatmapFrame.imageUrl}
                bounds={heatmapOverlay.coordinates}
                opacity={heatmapOverlay.opacity}
                zIndex={300}
              />
            )}
            {heatmapOverlay && currentHeatmapFrame && (
              <HeatmapLabelOverlay
                coordinates={heatmapOverlay.coordinates}
                label={currentHeatmapFrame.label}
              />
            )}
            <ZoomControl position="bottomright" />

            {drones.map((drone, index) => {
              const path = dronePaths[drone.id] ?? [];
              const isActive = activeDrone === drone.id;

              if (path.length < 2) return null;

              return (
                <Polyline
                  key={`${drone.id}-path`}
                  positions={path}
                  pathOptions={{
                    color: getDronePathColor(index),
                    weight: isActive ? 5 : 3,
                    opacity: isActive ? 0.9 : 0.6,
                    dashArray: isActive ? undefined : '6 8',
                  }}
                />
              );
            })}

            {drones.map((drone) => (
              <Marker key={drone.id} position={[drone.lat, drone.lng]} icon={createDroneIcon(drone.heading)}>
                <Popup className="rounded-lg">
                  <div className="p-1">
                    <h4 className="font-bold text-slate-800 border-b pb-1 mb-2">{formatDroneLabel(drone.id)}</h4>
                    <div className="space-y-1 text-sm">
                      <p><span className="text-slate-500">시동:</span> <span className={conditionTextClass(drone.armed)}>{formatArmed(drone.armed, drone.vehicleStatus)}</span></p>
                      <p><span className="text-slate-500">비행:</span> <span className={conditionTextClass(drone.flightEnable)}>{formatFlightEnable(drone.flightEnable, drone.vehicleStatus)}</span></p>
                      <p><span className="text-slate-500">배터리:</span> {formatBattery(drone.battery)}</p>
                      <p><span className="text-slate-500">전압:</span> {formatVoltage(drone.voltage)}</p>
                      <p><span className="text-slate-500">고도:</span> {formatMeters(drone.alt)}</p>
                      <p><span className="text-slate-500">상대고도:</span> {formatMeters(drone.relativeAlt)}</p>
                      <p><span className="text-slate-500">속력:</span> {formatSpeed(drone.va)}</p>
                      <p><span className="text-slate-500">헤딩:</span> {formatHeading(drone.heading)}</p>
                      <p><span className="text-slate-500">위치:</span> {drone.lat.toFixed(4)}, {drone.lng.toFixed(4)}</p>
                    </div>
                  </div>
                </Popup>
              </Marker>
            ))}

            {fires.map((fire) => (
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
