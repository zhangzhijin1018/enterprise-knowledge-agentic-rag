import { useState, useRef, useEffect } from 'react'
import { useParams } from 'react-router-dom'
import { Send, Loader2 } from 'lucide-react'
import { supervisorApi, type SupervisorChatResponse } from '@/services/api'
import clsx from 'clsx'

interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  timestamp: Date
  loading?: boolean
  // 经营分析相关字段
  analyticsData?: {
    summary?: string
    insight_cards?: any[]
    chart_spec?: any
    report_blocks?: any[]
    sql_preview?: string
    tables?: any[]
    row_count?: number
  }
  // 合同审查相关字段
  contractData?: {
    contract_file_id?: string
    contract_name?: string
    overall_risk_level?: string
    risk_items?: any[]
  }
}

// 合同文件状态
interface ContractFile {
  contract_file_id: string
  contract_name: string
  filename: string
}

export default function ChatPage() {
  const { conversationId } = useParams()
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [currentProgress, setCurrentProgress] = useState<string>('')
  const [progressPercent, setProgressPercent] = useState<number>(0)

  // 合同文件相关状态
  const [attachedContract, setAttachedContract] = useState<ContractFile | null>(null)
  const [isUploading, setIsUploading] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const messagesEndRef = useRef<HTMLDivElement>(null)
  const eventSourceRef = useRef<EventSource | null>(null)

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  useEffect(() => {
    scrollToBottom()
  }, [messages, currentProgress])

  // 清理 SSE 连接
  useEffect(() => {
    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close()
      }
    }
  }, [])

  /**
   * 订阅 SSE 事件流
   * - needs_sse=true: 接收进度 + 最终结果
   * - needs_sse=false: 只接收进度（结果已在 HTTP 响应中）
   */
  const subscribeSSE = (runId: string, assistantMessageId: string, needsSse: boolean) => {
    // 关闭之前的连接
    if (eventSourceRef.current) {
      eventSourceRef.current.close()
    }

    const eventSource = new EventSource(`/api/v1/stream/${runId}`)
    eventSourceRef.current = eventSource

    let isResultReceived = false

    // 连接成功
    eventSource.addEventListener('connected', () => {
      console.log('SSE 连接成功')
    })

    // 进度更新（所有场景都处理）
    eventSource.addEventListener('progress', (e) => {
      const data = JSON.parse(e.data)
      setCurrentProgress(data.current_step || '处理中...')
      setProgressPercent(data.progress || 0)

      // 更新消息状态
      setMessages((prev) =>
        prev.map((msg) =>
          msg.id === assistantMessageId
            ? { ...msg, loading: true }
            : msg
        )
      )
    })

    // 摘要完成
    eventSource.addEventListener('summary_done', (e) => {
      const data = JSON.parse(e.data)
      setProgressPercent(data.progress || 30)
    })

    // 洞察完成
    eventSource.addEventListener('insight_done', (e) => {
      const data = JSON.parse(e.data)
      setProgressPercent(data.progress || 60)
    })

    // 图表完成
    eventSource.addEventListener('chart_done', (e) => {
      const data = JSON.parse(e.data)
      setProgressPercent(data.progress || 80)
    })

    // 任务完成（只有 needs_sse=true 时才处理结果）
    eventSource.addEventListener('complete', (e) => {
      const data = JSON.parse(e.data)
      setProgressPercent(100)
      setCurrentProgress('完成')

      // 只有需要 SSE 结果时才更新消息
      if (needsSse && !isResultReceived) {
        isResultReceived = true
        const result = data.result || {}

        // 处理不同 Agent 的结果
        let content = ''
        let analyticsData: Message['analyticsData'] = undefined

        if (result.clarification) {
          // 澄清场景
          content = result.clarification.question || '需要更多信息来回答您的问题。'
        } else if (result.answer) {
          // RAG 结果
          content = result.answer
        } else if (result.summary) {
          // Analytics 结果
          content = result.summary
          analyticsData = {
            summary: result.summary,
            insight_cards: result.insight_cards,
            chart_spec: result.chart_spec,
            report_blocks: result.report_blocks,
            sql_preview: result.sql_preview,
            tables: result.tables,
            row_count: result.row_count,
          }
        } else if (result.review_report) {
          // Contract 结果
          content = formatContractReport(result.review_report)
        }

        setMessages((prev) =>
          prev.map((msg) =>
            msg.id === assistantMessageId
              ? {
                  ...msg,
                  content,
                  analyticsData,
                  loading: false,
                }
              : msg
          )
        )
      }

      // 清理
      setTimeout(() => {
        setCurrentProgress('')
        setProgressPercent(0)
        eventSource.close()
        if (!needsSse) {
          // 如果不需要 SSE 结果，关闭加载状态
          setIsLoading(false)
        }
      }, 500)
    })

    // 错误处理
    eventSource.addEventListener('error', (e) => {
      console.error('SSE 错误:', e)
      setMessages((prev) =>
        prev.map((msg) =>
          msg.id === assistantMessageId
            ? {
                ...msg,
                content: '抱歉，发生了错误，请稍后重试。',
                loading: false,
              }
            : msg
        )
      )
      setCurrentProgress('')
      setProgressPercent(0)
      eventSource.close()
      setIsLoading(false)
    })
  }

  /**
   * 格式化合同审查报告
   */
  const formatContractReport = (report: any): string => {
    if (!report) return '合同审查完成。'

    const lines = []
    lines.push('=' .repeat(50))
    lines.push('合同审查报告')
    lines.push('='.repeat(50))
    lines.push('')
    lines.push(`合同名称：${report.contract_name || '未知'}`)
    lines.push(`合同类型：${report.contract_type?.value || '未知'}`)
    lines.push('')

    if (report.risk_summary) {
      lines.push('风险概要：')
      lines.push(`  ${report.risk_summary}`)
      lines.push('')
    }

    const high = report.high_risk_count || 0
    const medium = report.medium_risk_count || 0
    const low = report.low_risk_count || 0
    lines.push(`风险统计：高风险 ${high} 项，中风险 ${medium} 项，低风险 ${low} 项`)
    lines.push('')

    if (report.conclusion) {
      lines.push('审查结论：')
      lines.push(`  ${report.conclusion}`)
      lines.push('')
    }

    lines.push('='.repeat(50))
    return lines.join('\n')
  }

  /**
   * 处理合同文件上传
   */
  const handleContractUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return

    // 验证文件类型
    const allowedTypes = ['.pdf', '.doc', '.docx', '.txt']
    const ext = '.' + file.name.split('.').pop()?.toLowerCase()
    if (!allowedTypes.includes(ext)) {
      alert('仅支持 PDF、Word、TXT 格式的文件')
      return
    }

    setIsUploading(true)

    try {
      const formData = new FormData()
      formData.append('file', file)
      formData.append('contract_name', file.name.replace(/\.[^.]+$/, ''))
      formData.append('contract_type', '未知类型')

      const response = await fetch('/api/v1/contracts/upload', {
        method: 'POST',
        body: formData,
      })

      if (!response.ok) {
        throw new Error('上传失败')
      }

      const result = await response.json()
      const contractFile: ContractFile = {
        contract_file_id: result.data.contract_file_id,
        contract_name: result.data.contract_name,
        filename: result.data.filename,
      }

      setAttachedContract(contractFile)
    } catch (error) {
      console.error('上传合同文件失败:', error)
      alert('上传失败，请重试')
    } finally {
      setIsUploading(false)
      if (fileInputRef.current) {
        fileInputRef.current.value = ''
      }
    }
  }

  /**
   * 移除已上传的合同文件
   */
  const handleRemoveContract = () => {
    setAttachedContract(null)
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!input.trim() || isLoading) return

    const userMessage: Message = {
      id: Date.now().toString(),
      role: 'user',
      content: input.trim(),
      timestamp: new Date(),
    }

    setMessages((prev) => [...prev, userMessage])
    setInput('')
    setIsLoading(true)

    // 添加一个占位消息
    const assistantMessageId = (Date.now() + 1).toString()
    setMessages((prev) => [
      ...prev,
      {
        id: assistantMessageId,
        role: 'assistant',
        content: '',
        timestamp: new Date(),
        loading: true,
        contractData: attachedContract ? {
          contract_file_id: attachedContract.contract_file_id,
          contract_name: attachedContract.contract_name,
        } : undefined,
      },
    ])

    try {
      // 调用统一入口（传入合同文件 ID）
      const response = await supervisorApi.chat({
        query: userMessage.content,
        conversation_id: conversationId,
        contract_file_id: attachedContract?.contract_file_id,
        contract_name: attachedContract?.contract_name,
      })

      const result = response.data

      // 所有场景都订阅 SSE 获取进度（只是是否等待 SSE 结果不同）
      subscribeSSE(result.run_id, assistantMessageId, result.needs_sse)

      // 如果需要 SSE 结果（慢速场景），等待 SSE 推送
      // 如果不需要 SSE 结果（快速场景），直接使用 HTTP 响应结果
      if (!result.needs_sse) {
        if (result.needs_clarification) {
          // 澄清场景
          setMessages((prev) =>
            prev.map((msg) =>
              msg.id === assistantMessageId
                ? {
                    ...msg,
                    content: result.clarification_questions?.join('\n') ||
                             '需要更多信息来回答您的问题。',
                    loading: false,
                  }
                : msg
            )
          )
        } else {
          // 快速场景（RAG 等）：直接使用 HTTP 响应结果
          setMessages((prev) =>
            prev.map((msg) =>
              msg.id === assistantMessageId
                ? {
                    ...msg,
                    content: result.answer || '处理完成。',
                    loading: false,
                  }
                : msg
            )
          )
        }
        setIsLoading(false)
      }
      // 如果 needs_sse=true，则等待 SSE complete 事件后更新消息
    } catch (error) {
      console.error('请求失败:', error)
      setMessages((prev) =>
        prev.map((msg) =>
          msg.id === assistantMessageId
            ? {
                ...msg,
                content: '抱歉，发生了错误，请稍后重试。',
                loading: false,
              }
            : msg
        )
      )
      setIsLoading(false)
    }
  }

  return (
    <div className="h-full flex flex-col">
      {/* 头部 */}
      <div className="px-6 py-4 border-b border-gray-200 bg-white">
        <h1 className="text-xl font-semibold text-gray-900">智能问答</h1>
        <p className="text-sm text-gray-500 mt-1">
          基于企业知识库的专业问答助手
        </p>
      </div>

      {/* 消息列表 */}
      <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full text-center">
            <div className="w-16 h-16 rounded-full bg-primary-100 flex items-center justify-center mb-4">
              <Send className="w-8 h-8 text-primary-600" />
            </div>
            <h2 className="text-lg font-medium text-gray-900 mb-2">
              开始提问吧
            </h2>
            <p className="text-gray-500 max-w-md">
              您可以询问关于集团制度、安全规程、设备检修、经营分析等方面的问题，我会尽力为您提供准确的答案。
            </p>
          </div>
        )}

        {messages.map((message) => (
          <div
            key={message.id}
            className={clsx(
              'animate-fade-in',
              message.role === 'user' ? 'flex justify-end' : 'flex justify-start'
            )}
          >
            <div
              className={clsx(
                'max-w-[70%] rounded-lg p-4',
                message.role === 'user'
                  ? 'chat-message chat-message-user'
                  : 'chat-message chat-message-assistant'
              )}
            >
              {message.loading ? (
                <div className="space-y-3">
                  <div className="flex items-center gap-2 text-gray-500">
                    <Loader2 className="w-4 h-4 animate-spin" />
                    <span>正在思考...</span>
                  </div>
                  {/* 进度展示 */}
                  {currentProgress && (
                    <div className="space-y-1">
                      <div className="text-sm text-gray-500">{currentProgress}</div>
                      <div className="w-full bg-gray-200 rounded-full h-1.5">
                        <div
                          className="bg-primary-600 h-1.5 rounded-full transition-all duration-300"
                          style={{ width: `${progressPercent}%` }}
                        />
                      </div>
                    </div>
                  )}
                </div>
              ) : (
                <>
                  <div className="prose prose-sm max-w-none">
                    <p className="whitespace-pre-wrap">{message.content}</p>
                  </div>

                  {/* 经营分析数据展示 */}
                  {message.analyticsData && (
                    <div className="mt-4 pt-4 border-t border-gray-200 space-y-4">
                      {/* SQL 预览 */}
                      {message.analyticsData.sql_preview && (
                        <div>
                          <h4 className="text-xs font-medium text-gray-500 mb-1">SQL 预览</h4>
                          <pre className="text-xs bg-gray-50 p-2 rounded overflow-x-auto">
                            {message.analyticsData.sql_preview}
                          </pre>
                        </div>
                      )}

                      {/* 数据表格 */}
                      {message.analyticsData.tables && message.analyticsData.tables.length > 0 && (
                        <div>
                          <h4 className="text-xs font-medium text-gray-500 mb-1">
                            查询结果 ({message.analyticsData.row_count} 行)
                          </h4>
                          <div className="overflow-x-auto">
                            <table className="min-w-full text-xs">
                              <thead className="bg-gray-50">
                                <tr>
                                  {message.analyticsData.tables[0].columns?.map((col: string, i: number) => (
                                    <th key={i} className="px-2 py-1 text-left font-medium">{col}</th>
                                  ))}
                                </tr>
                              </thead>
                              <tbody>
                                {message.analyticsData.tables[0].rows?.slice(0, 5).map((row: any[], i: number) => (
                                  <tr key={i} className="border-t">
                                    {row.map((cell: any, j: number) => (
                                      <td key={j} className="px-2 py-1">{String(cell)}</td>
                                    ))}
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        </div>
                      )}

                      {/* 洞察卡片 */}
                      {message.analyticsData.insight_cards && message.analyticsData.insight_cards.length > 0 && (
                        <div>
                          <h4 className="text-xs font-medium text-gray-500 mb-2">关键洞察</h4>
                          <div className="space-y-2">
                            {message.analyticsData.insight_cards.map((card: any, i: number) => (
                              <div key={i} className="bg-primary-50 rounded p-2 text-xs">
                                <div className="font-medium text-primary-700">{card.title}</div>
                                <div className="text-gray-600 mt-1">{card.summary}</div>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </>
              )}
            </div>
          </div>
        ))}
        <div ref={messagesEndRef} />
      </div>

      {/* 输入框 */}
      <div className="px-6 py-4 border-t border-gray-200 bg-white">
        <form onSubmit={handleSubmit} className="space-y-3">
          {/* 合同文件附件 */}
          {attachedContract && (
            <div className="flex items-center gap-2 p-2 bg-blue-50 rounded-lg">
              <span className="text-sm text-blue-700">📎 已附加合同:</span>
              <span className="text-sm font-medium text-blue-900">{attachedContract.filename}</span>
              <button
                type="button"
                onClick={handleRemoveContract}
                className="ml-auto text-blue-500 hover:text-blue-700"
              >
                ✕
              </button>
            </div>
          )}

          <div className="flex gap-3">
            {/* 合同上传按钮 */}
            <div className="flex items-center">
              <label className="cursor-pointer p-2 hover:bg-gray-100 rounded-lg" title="上传合同文件">
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".pdf,.doc,.docx,.txt"
                  onChange={handleContractUpload}
                  className="hidden"
                />
                {isUploading ? (
                  <Loader2 className="w-5 h-5 animate-spin text-gray-500" />
                ) : (
                  <span className="text-xl">📎</span>
                )}
              </label>
            </div>

            {/* 消息输入框 */}
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="输入您的问题，或上传合同文件进行审查..."
              className="input flex-1"
              disabled={isLoading}
            />

            {/* 发送按钮 */}
            <button
              type="submit"
              disabled={!input.trim() || isLoading}
              className="btn-primary px-6 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {isLoading ? (
                <Loader2 className="w-5 h-5 animate-spin" />
              ) : (
                <Send className="w-5 h-5" />
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
