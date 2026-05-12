import axios from 'axios';

// 백엔드 Base URL 설정 (환경 변수 또는 기본값)
export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8080/api';

// Mock 데이터 사용 여부 플래그 (환경 변수 VITE_USE_MOCK_DATA가 'false'이면 API 호출)
export const USE_MOCK_DATA = import.meta.env.VITE_USE_MOCK_DATA !== 'false';

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

// API 설정 변경 함수 (런타임에 Base URL을 변경해야 할 경우 사용)
export const setApiBaseUrl = (url: string) => {
  apiClient.defaults.baseURL = url;
};
