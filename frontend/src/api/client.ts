/**
 * Bible RAG - API Client
 *
 * Axios-based HTTP client with request/response interceptors.
 */

import axios from 'axios';
import type { AxiosError, AxiosResponse, InternalAxiosRequestConfig } from 'axios';
import { API_CONFIG } from '@/utils/constants';
import type { ApiError } from '@/types';

/** Create axios instance */
const apiClient = axios.create({
  baseURL: API_CONFIG.BASE_URL,
  timeout: API_CONFIG.TIMEOUT,
  headers: {
    'Content-Type': 'application/json',
  },
});

/** Request interceptor */
apiClient.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    // Add any request modifications here (e.g., auth tokens)
    // const token = localStorage.getItem('token');
    // if (token) {
    //   config.headers.Authorization = `Bearer ${token}`;
    // }
    return config;
  },
  (error: AxiosError) => {
    console.error('[API Request Error]', error);
    return Promise.reject(error);
  }
);

/** Response interceptor */
apiClient.interceptors.response.use(
  (response: AxiosResponse) => {
    return response;
  },
  (error: AxiosError<ApiError>) => {
    // Handle common error cases
    if (error.response) {
      const { status, data } = error.response;

      switch (status) {
        case 400:
          console.error('[API Bad Request]', data?.detail || 'Bad request');
          break;
        case 404:
          console.error('[API Not Found]', data?.detail || 'Resource not found');
          break;
        case 422:
          console.error('[API Validation Error]', data?.detail || 'Validation failed');
          break;
        case 500:
          console.error('[API Server Error]', data?.detail || 'Internal server error');
          break;
        case 503:
          console.error('[API Service Unavailable]', data?.detail || 'Service unavailable');
          break;
        default:
          console.error('[API Error]', status, data?.detail || 'Unknown error');
      }
    } else if (error.request) {
      console.error('[API Network Error]', 'No response received from server');
    } else {
      console.error('[API Error]', error.message);
    }

    return Promise.reject(error);
  }
);

export default apiClient;
