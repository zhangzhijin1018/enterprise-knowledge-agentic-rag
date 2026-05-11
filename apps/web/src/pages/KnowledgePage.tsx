import { useState, useRef } from 'react'
import { BookOpen, Upload, FileText, Loader2, Search, Filter } from 'lucide-react'
import { documentApi, type Document } from '@/services/api'
import clsx from 'clsx'

export default function KnowledgePage() {
  const [documents, setDocuments] = useState<Document[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
  const [uploadProgress, setUploadProgress] = useState(0)
  const [searchQuery, setSearchQuery] = useState('')
  const [filterStatus, setFilterStatus] = useState<string>('all')
  const fileInputRef = useRef<HTMLInputElement>(null)

  // 加载文档列表
  useState(() => {
    documentApi.list({ limit: 100 })
      .then((res) => setDocuments(res.data.items))
      .finally(() => setIsLoading(false))
  })

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return

    setUploading(true)
    setUploadProgress(0)

    try {
      const progressInterval = setInterval(() => {
        setUploadProgress((prev) => Math.min(prev + 10, 90))
      }, 200)

      await documentApi.upload(file, (percent) => {
        setUploadProgress(percent)
      })

      clearInterval(progressInterval)
      setUploadProgress(100)

      // 刷新列表
      const res = await documentApi.list({ limit: 100 })
      setDocuments(res.data.items)
    } catch (error) {
      console.error('Upload failed:', error)
    } finally {
      setUploading(false)
      setUploadProgress(0)
    }
  }

  const filteredDocuments = documents.filter((doc) => {
    const matchesSearch = doc.filename.toLowerCase().includes(searchQuery.toLowerCase())
    const matchesFilter = filterStatus === 'all' || doc.status === filterStatus
    return matchesSearch && matchesFilter
  })

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'completed':
        return 'bg-success-50 text-success-700'
      case 'processing':
        return 'bg-warning-50 text-warning-700'
      case 'failed':
        return 'bg-danger-50 text-danger-700'
      default:
        return 'bg-gray-50 text-gray-700'
    }
  }

  const getFileIcon = (fileType: string) => {
    switch (fileType.toLowerCase()) {
      case 'pdf':
        return '📄'
      case 'doc':
      case 'docx':
        return '📝'
      case 'xls':
      case 'xlsx':
        return '📊'
      default:
        return '📄'
    }
  }

  return (
    <div className="h-full flex flex-col">
      {/* 头部 */}
      <div className="px-6 py-4 border-b border-gray-200 bg-white">
        <h1 className="text-xl font-semibold text-gray-900">知识库</h1>
        <p className="text-sm text-gray-500 mt-1">
          管理企业知识库文档，支持全文检索和智能问答
        </p>
      </div>

      <div className="flex-1 overflow-auto p-6">
        {/* 操作栏 */}
        <div className="flex items-center justify-between mb-6">
          {/* 搜索 */}
          <div className="flex-1 max-w-md">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-400" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="搜索文档..."
                className="input pl-10"
              />
            </div>
          </div>

          {/* 过滤 */}
          <div className="flex items-center gap-4 ml-4">
            <select
              value={filterStatus}
              onChange={(e) => setFilterStatus(e.target.value)}
              className="input w-40"
            >
              <option value="all">全部状态</option>
              <option value="completed">已完成</option>
              <option value="processing">处理中</option>
              <option value="failed">失败</option>
            </select>

            {/* 上传按钮 */}
            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={uploading}
              className="btn-primary flex items-center gap-2"
            >
              {uploading ? (
                <>
                  <Loader2 className="w-5 h-5 animate-spin" />
                  上传中... {uploadProgress}%
                </>
              ) : (
                <>
                  <Upload className="w-5 h-5" />
                  上传文档
                </>
              )}
            </button>
            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf,.doc,.docx,.txt,.xls,.xlsx"
              onChange={handleFileChange}
              className="hidden"
            />
          </div>
        </div>

        {/* 文档列表 */}
        {isLoading ? (
          <div className="text-center py-12 text-gray-500">
            <Loader2 className="w-8 h-8 animate-spin mx-auto mb-4" />
            加载中...
          </div>
        ) : filteredDocuments.length === 0 ? (
          <div className="text-center py-12">
            <BookOpen className="w-16 h-16 text-gray-300 mx-auto mb-4" />
            <h3 className="text-lg font-medium text-gray-700 mb-2">
              {documents.length === 0 ? '暂无文档' : '未找到匹配的文档'}
            </h3>
            <p className="text-gray-500 mb-4">
              {documents.length === 0
                ? '上传您的第一个文档开始构建知识库'
                : '尝试调整搜索条件'}
            </p>
            {documents.length === 0 && (
              <button
                onClick={() => fileInputRef.current?.click()}
                className="btn-primary"
              >
                <Upload className="w-5 h-5 mr-2" />
                上传文档
              </button>
            )}
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
            {filteredDocuments.map((doc) => (
              <div
                key={doc.document_id}
                className="card hover:shadow-md transition-shadow cursor-pointer"
              >
                <div className="p-4">
                  <div className="flex items-start gap-3 mb-3">
                    <div className="text-3xl">{getFileIcon(doc.file_type)}</div>
                    <div className="flex-1 min-w-0">
                      <h3 className="font-medium text-gray-900 truncate" title={doc.filename}>
                        {doc.filename}
                      </h3>
                      <p className="text-sm text-gray-500">
                        {doc.file_type.toUpperCase()} · {(doc.size / 1024 / 1024).toFixed(2)} MB
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center justify-between">
                    <span
                      className={clsx(
                        'px-2 py-1 rounded text-xs font-medium',
                        getStatusColor(doc.status)
                      )}
                    >
                      {doc.status === 'completed' && '已完成'}
                      {doc.status === 'processing' && '处理中'}
                      {doc.status === 'failed' && '失败'}
                    </span>
                    <span className="text-xs text-gray-400">
                      {doc.chunk_count || 0} 个切片
                    </span>
                  </div>
                  <div className="mt-3 pt-3 border-t border-gray-100">
                    <p className="text-xs text-gray-400">
                      {new Date(doc.created_at).toLocaleDateString()}
                    </p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
