/**
 * Bible RAG - Books API Endpoints
 *
 * Book-related API calls.
 */

import apiClient from '../client';
import type {
  BookChaptersResponse,
  BookDetail,
  BookPericopesResponse,
  BookVersesResponse,
  BooksListResponse,
} from '@/types';

/** Books API */
export const booksApi = {
  /**
   * Get all books
   * @returns Books list response
   */
  getAll: async (): Promise<BooksListResponse> => {
    const response = await apiClient.get<BooksListResponse>('/books');
    return response.data;
  },

  /**
   * Get book by ID
   * @param bookId - Book ID
   * @returns Book detail
   */
  getById: async (bookId: number): Promise<BookDetail> => {
    const response = await apiClient.get<BookDetail>(`/books/${bookId}`);
    return response.data;
  },

  /**
   * Get book chapters
   * @param bookId - Book ID
   * @returns Book chapters response
   */
  getChapters: async (bookId: number): Promise<BookChaptersResponse> => {
    const response = await apiClient.get<BookChaptersResponse>(
      `/books/${bookId}/chapters`
    );
    return response.data;
  },

  /**
   * Get book pericopes
   * @param bookId - Book ID
   * @returns Book pericopes response
   */
  getPericopes: async (bookId: number): Promise<BookPericopesResponse> => {
    const response = await apiClient.get<BookPericopesResponse>(
      `/books/${bookId}/pericopes`
    );
    return response.data;
  },

  /**
   * Get book verses
   * @param bookId - Book ID
   * @param chapter - Optional chapter filter
   * @returns Book verses response
   */
  getVerses: async (
    bookId: number,
    chapter?: number
  ): Promise<BookVersesResponse> => {
    const params = chapter ? { chapter } : undefined;
    const response = await apiClient.get<BookVersesResponse>(
      `/books/${bookId}/verses`,
      { params }
    );
    return response.data;
  },
};
