import axios from 'axios'

const API_BASE_URL = import.meta.env.VITE_API_URL || '/api/v1'

const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// 请求拦截器
apiClient.interceptors.request.use(
  (config) => {
    // 添加认证 token
    const token = localStorage.getItem('token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

// 响应拦截器
apiClient.interceptors.response.use(
  (response) => {
    return response.data
  },
  (error) => {
    const message = error.response?.data?.message || error.message
    console.error('API Error:', message)
    return Promise.reject(error)
  }
)

// ==================== 统一入口（Supervisor）API ====================

export interface SupervisorChatRequest {
  query: string
  conversation_id?: string
  user_id?: string
  user_role?: string
  department_code?: string
  // 合同审查相关参数
  contract_file_id?: string
  contract_name?: string
  contract_type?: string
}

export interface SupervisorChatResponse {
  run_id: string
  trace_id: string
  conversation_id?: string
  intent: string
  needs_sse: boolean
  answer?: string
  status: string
  routing_target: string
  needs_clarification: boolean
  clarification_questions?: string[]
  metadata?: Record<string, any>
}

export const supervisorApi = {
  chat: (data: SupervisorChatRequest) =>
    apiClient.post<SupervisorChatResponse>('/chat', data),
}

// ==================== RAG 问答 API ====================

export interface RAGQueryRequest {
  query: string
  conversation_id?: string
  business_domain?: string
  knowledge_base_ids?: string[]
}

export interface RAGQueryResponse {
  run_id: string
  query: string
  answer: string
  citations: Citation[]
  outcome: string
  processing_time_ms: number
}

export interface Citation {
  citation_id: string
  chunk_uuid: string
  content: string
  score: number
  section_title?: string
  page_start?: number
}

export const ragApi = {
  query: (data: RAGQueryRequest) =>
    apiClient.post<RAGQueryResponse>('/rag/query', null, { params: data }),

  getRun: (runId: string) =>
    apiClient.get<RAGQueryResponse>(`/rag/run/${runId}`),
}

// ==================== 经营分析 API ====================

export interface AnalyticsQueryRequest {
  query: string
  output_mode?: 'lite' | 'standard' | 'full'
  conversation_id?: string
}

export interface AnalyticsQueryResponse {
  run_id: string
  status: string
  result?: {
    sql: string
    data: any[]
    summary: string
    charts?: any[]
  }
  processing_time_ms: number
}

export const analyticsApi = {
  query: (data: AnalyticsQueryRequest) =>
    apiClient.post<AnalyticsQueryResponse>('/analytics/query', data),

  getRun: (runId: string) =>
    apiClient.get<AnalyticsQueryResponse>(`/analytics/run/${runId}`),
}

// ==================== 合同审查 API ====================

export interface ContractReviewRequest {
  contract_file_id: string
  contract_name?: string
  contract_type?: string
  business_domain?: string
}

export interface ContractReviewResponse {
  review_id: string
  contract_id: string
  contract_name: string
  contract_type: string
  overall_risk_level: string
  status: string
  need_human_review: boolean
  report?: ContractReport
  processing_time_ms: number
}

export interface ContractReport {
  report_id: string
  risk_summary: string
  risks: Risk[]
  suggestions: string[]
  conclusion: string
}

export interface Risk {
  risk_id: string
  risk_type: string
  risk_category: string
  risk_description: string
  related_clause: string
  suggestion: string
}

export const contractApi = {
  review: (data: ContractReviewRequest) =>
    apiClient.post<ContractReviewResponse>('/contract/review', data),

  getReview: (reviewId: string) =>
    apiClient.get<ContractReviewResponse>(`/contract/${reviewId}`),
}

// ==================== 审核 API ====================

export interface ReviewListItem {
  review_id: string
  task_type: string
  risk_level: string
  title: string
  status: string
  submitted_at: string
  assigned_to?: string
}

export interface ReviewDecisionRequest {
  decision: 'approve' | 'reject' | 'revise'
  reason?: string
  revised_content?: string
}

export const reviewApi = {
  list: (params?: { status?: string; task_type?: string; limit?: number }) =>
    apiClient.get<{ items: ReviewListItem[]; total: number }>('/reviews', { params }),

  get: (reviewId: string) =>
    apiClient.get<ReviewListItem>(`/reviews/${reviewId}`),

  assign: (reviewId: string, assignedTo: string) =>
    apiClient.post(`/reviews/${reviewId}/assign`, null, { params: { assigned_to: assignedTo } }),

  decision: (reviewId: string, data: ReviewDecisionRequest) =>
    apiClient.post(`/reviews/${reviewId}/decision`, data),

  cancel: (reviewId: string, reason?: string) =>
    apiClient.post(`/reviews/${reviewId}/cancel`, null, { params: { reason } }),

  statistics: () =>
    apiClient.get<{
      total: number
      pending: number
      in_review: number
      approved: number
      rejected: number
    }>('/reviews/statistics/summary'),
}

// ==================== 文档 API ====================

export interface Document {
  document_id: string
  filename: string
  file_type: string
  status: string
  created_at: string
  chunk_count?: number
}

export const documentApi = {
  list: (params?: { status?: string; limit?: number }) =>
    apiClient.get<{ items: Document[]; total: number }>('/documents', { params }),

  get: (documentId: string) =>
    apiClient.get<Document>(`/documents/${documentId}`),

  upload: (file: File, onProgress?: (percent: number) => void) => {
    const formData = new FormData()
    formData.append('file', file)

    return apiClient.post<Document>('/documents/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      onUploadProgress: (e) => {
        if (e.total && onProgress) {
          onProgress(Math.round((e.loaded * 100) / e.total))
        }
      },
    })
  },
}

// ==================== 会话 API ====================

export interface Conversation {
  conversation_id: string
  title: string
  message_count: number
  created_at: string
  updated_at: string
}

export interface Message {
  message_id: string
  role: 'user' | 'assistant'
  content: string
  created_at: string
  metadata?: Record<string, any>
}

export const conversationApi = {
  list: (params?: { limit?: number }) =>
    apiClient.get<{ items: Conversation[]; total: number }>('/conversations', { params }),

  get: (conversationId: string) =>
    apiClient.get<{ conversation: Conversation; messages: Message[] }>(
      `/conversations/${conversationId}`
    ),

  create: (title?: string) =>
    apiClient.post<Conversation>('/conversations', { title }),

  delete: (conversationId: string) =>
    apiClient.delete(`/conversations/${conversationId}`),
}

export default apiClient
