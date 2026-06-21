export interface KnowledgeBase {
  knowledge_id: number
  title: string
  category: string
}

export interface Document {
  document_id: number
  knowledge_id: number
  title: string
  category: string
  file_type: string
  process_status: 'pending' | 'processing' | 'completed' | 'failed'
}

export interface LoginResponse {
  access_token: string
  token_type: string
  username: string
}

export interface ChatMessage {
  role: 'user' | 'assistant' | 'system'
  content: string
}

export interface RAGSource {
  document_id: number
  document_name: string
  page_number: number
  chunk_content: string
}

export interface KnowledgeBaseCreateRequest {
  title: string
  category: string
}
