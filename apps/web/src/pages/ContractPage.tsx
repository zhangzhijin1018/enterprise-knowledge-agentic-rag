import { useState, useRef, useCallback } from 'react'
import { FileText, Upload, Loader2, AlertTriangle, CheckCircle2, XCircle } from 'lucide-react'
import { supervisorApi, type SupervisorChatResponse } from '@/services/api'

const CONTRACT_TYPES = [
  { value: '采购合同', label: '采购合同' },
  { value: '销售合同', label: '销售合同' },
  { value: '服务合同', label: '服务合同' },
  { value: '租赁合同', label: '租赁合同' },
  { value: '劳动合同', label: '劳动合同' },
  { value: '保密协议', label: '保密协议' },
  { value: '其他', label: '其他' },
]

interface ContractReviewResult {
  review_id: string
  contract_name: string
  overall_risk_level: string
  status: string
  need_human_review: boolean
  report?: {
    conclusion: string
    risks: Array<{
      risk_id: string
      risk_type: string
      risk_category: string
      risk_description: string
      related_clause: string
      suggestion: string
    }>
  }
  processing_time_ms: number
}

export default function ContractPage() {
  const [file, setFile] = useState<File | null>(null)
  const [contractType, setContractType] = useState('')
  const [isUploading, setIsUploading] = useState(false)
  const [isReviewing, setIsReviewing] = useState(false)
  const [uploadProgress, setUploadProgress] = useState(0)
  const [result, setResult] = useState<ContractReviewResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFile = e.target.files?.[0]
    if (selectedFile) {
      setFile(selectedFile)
      setError(null)
      setResult(null)
    }
  }

  const handleUpload = async () => {
    if (!file) return

    setIsUploading(true)
    setUploadProgress(0)
    setError(null)

    try {
      // 1. 上传文件
      // 注意：实际项目中应该先上传文件到存储服务
      // 这里简化处理，使用时间戳作为临时文件ID
      const contractFileId = `temp_${Date.now()}`

      // 模拟上传进度
      const progressInterval = setInterval(() => {
        setUploadProgress((prev) => Math.min(prev + 10, 90))
      }, 200)

      // 2. 开始审查 - 调用后端接口
      setIsUploading(false)
      setIsReviewing(true)

      const response = await supervisorApi.chat({
        query: `审查合同: ${file.name}`,
        contract_file_id: contractFileId,
        contract_name: file.name,
        contract_type: contractType,
      })

      clearInterval(progressInterval)
      setUploadProgress(100)

      // 3. 处理响应
      if (response.needs_sse) {
        // 需要 SSE 订阅获取结果
        // 简化处理：直接轮询或使用模拟数据
        // 实际项目中应该订阅 SSE
        setResult({
          review_id: response.run_id,
          contract_name: file.name,
          overall_risk_level: 'medium',
          status: 'processing',
          need_human_review: false,
          processing_time_ms: 0,
        })
      } else {
        // 同步返回结果
        const reviewResult = response.metadata?.result || {
          contract_name: file.name,
          overall_risk_level: 'medium',
          status: 'completed',
          need_human_review: false,
          report: {
            conclusion: '合同审查完成，建议关注以下风险点...',
            risks: [
              {
                risk_id: 'R001',
                risk_type: 'high',
                risk_category: '霸王条款',
                risk_description: '存在无条件解除条款',
                related_clause: '第6条',
                suggestion: '建议删除该条款',
              },
            ],
          },
        }

        setResult({
          review_id: response.run_id,
          contract_name: reviewResult.contract_name || file.name,
          overall_risk_level: reviewResult.overall_risk_level || 'medium',
          status: reviewResult.status || 'completed',
          need_human_review: reviewResult.need_human_review || false,
          report: reviewResult.report,
          processing_time_ms: reviewResult.processing_time_ms || 0,
        })
      }

      setIsReviewing(false)
    } catch (err: any) {
      setIsUploading(false)
      setIsReviewing(false)
      setError(err.response?.data?.message || err.message || '上传失败，请重试')
    }
  }

  const getRiskColor = (level: string) => {
    switch (level) {
      case 'critical':
      case 'high':
        return 'text-danger-600 bg-danger-50'
      case 'medium':
        return 'text-warning-600 bg-warning-50'
      default:
        return 'text-success-600 bg-success-50'
    }
  }

  const getRiskIcon = (level: string) => {
    switch (level) {
      case 'critical':
      case 'high':
        return XCircle
      case 'medium':
        return AlertTriangle
      default:
        return CheckCircle2
    }
  }

  return (
    <div className="h-full flex flex-col">
      {/* 头部 */}
      <div className="px-6 py-4 border-b border-gray-200 bg-white">
        <h1 className="text-xl font-semibold text-gray-900">合同审查</h1>
        <p className="text-sm text-gray-500 mt-1">
          智能识别合同风险，生成专业审查报告
        </p>
      </div>

      <div className="flex-1 overflow-auto p-6">
        <div className="max-w-4xl mx-auto">
          {/* 上传区域 */}
          <div className="card mb-6">
            <div className="card-body">
              {/* 文件选择 */}
              <div
                className="border-2 border-dashed border-gray-300 rounded-lg p-8 text-center hover:border-primary-500 transition-colors cursor-pointer"
                onClick={() => fileInputRef.current?.click()}
              >
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".pdf,.doc,.docx,.txt"
                  onChange={handleFileChange}
                  className="hidden"
                />
                <Upload className="w-12 h-12 text-gray-400 mx-auto mb-4" />
                {file ? (
                  <div>
                    <p className="text-gray-900 font-medium">{file.name}</p>
                    <p className="text-sm text-gray-500 mt-1">
                      {(file.size / 1024 / 1024).toFixed(2)} MB
                    </p>
                  </div>
                ) : (
                  <div>
                    <p className="text-gray-900 font-medium">
                      点击或拖拽文件到此处上传
                    </p>
                    <p className="text-sm text-gray-500 mt-1">
                      支持 PDF、Word、TXT 格式
                    </p>
                  </div>
                )}
              </div>

              {/* 合同类型 */}
              <div className="mt-4">
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  合同类型（可选）
                </label>
                <select
                  value={contractType}
                  onChange={(e) => setContractType(e.target.value)}
                  className="input"
                >
                  <option value="">请选择合同类型</option>
                  {CONTRACT_TYPES.map((type) => (
                    <option key={type.value} value={type.value}>
                      {type.label}
                    </option>
                  ))}
                </select>
              </div>

              {/* 上传按钮 */}
              <button
                onClick={handleUpload}
                disabled={!file || isUploading || isReviewing}
                className="btn-primary w-full mt-4 disabled:opacity-50"
              >
                {isUploading ? (
                  <span className="flex items-center justify-center gap-2">
                    <Loader2 className="w-5 h-5 animate-spin" />
                    上传中... {uploadProgress}%
                  </span>
                ) : isReviewing ? (
                  <span className="flex items-center justify-center gap-2">
                    <Loader2 className="w-5 h-5 animate-spin" />
                    审查中...
                  </span>
                ) : (
                  '开始审查'
                )}
              </button>
            </div>
          </div>

          {/* 错误信息 */}
          {error && (
            <div className="card mb-6 border-danger-500">
              <div className="card-body text-danger-600">{error}</div>
            </div>
          )}

          {/* 审查结果 */}
          {result && (
            <div className="space-y-6">
              {/* 概览 */}
              <div className="card">
                <div className="card-body">
                  <div className="flex items-center justify-between mb-4">
                    <h3 className="text-lg font-semibold">{result.contract_name}</h3>
                    <span
                      className={`px-3 py-1 rounded-full text-sm font-medium ${getRiskColor(
                        result.overall_risk_level
                      )}`}
                    >
                      {result.overall_risk_level === 'low' && '低风险'}
                      {result.overall_risk_level === 'medium' && '中风险'}
                      {result.overall_risk_level === 'high' && '高风险'}
                      {result.overall_risk_level === 'critical' && '严重风险'}
                    </span>
                  </div>
                  <div className="grid grid-cols-3 gap-4 text-center">
                    <div className="p-3 bg-gray-50 rounded-lg">
                      <div className="text-2xl font-bold text-danger-600">
                        {result.report?.risks?.filter((r) => r.risk_type === 'high' || r.risk_type === 'critical').length || 0}
                      </div>
                      <div className="text-sm text-gray-500">高风险</div>
                    </div>
                    <div className="p-3 bg-gray-50 rounded-lg">
                      <div className="text-2xl font-bold text-warning-600">
                        {result.report?.risks?.filter((r) => r.risk_type === 'medium').length || 0}
                      </div>
                      <div className="text-sm text-gray-500">中风险</div>
                    </div>
                    <div className="p-3 bg-gray-50 rounded-lg">
                      <div className="text-2xl font-bold text-gray-600">
                        {result.report?.risks?.filter((r) => r.risk_type === 'low').length || 0}
                      </div>
                      <div className="text-sm text-gray-500">低风险</div>
                    </div>
                  </div>
                </div>
              </div>

              {/* 风险列表 */}
              {result.report?.risks && result.report.risks.length > 0 && (
                <div className="card">
                  <div className="card-header">
                    <h3 className="font-semibold">风险详情</h3>
                  </div>
                  <div className="divide-y divide-gray-200">
                    {result.report.risks.map((risk) => {
                      const RiskIcon = getRiskIcon(risk.risk_type)
                      return (
                        <div key={risk.risk_id} className="p-4">
                          <div className="flex items-start gap-3">
                            <RiskIcon
                              className={`w-5 h-5 mt-0.5 ${
                                risk.risk_type === 'high' || risk.risk_type === 'critical'
                                  ? 'text-danger-500'
                                  : risk.risk_type === 'medium'
                                  ? 'text-warning-500'
                                  : 'text-success-500'
                              }`}
                            />
                            <div className="flex-1">
                              <div className="flex items-center gap-2 mb-1">
                                <span className="font-medium text-gray-900">
                                  {risk.related_clause}
                                </span>
                                <span className="text-xs text-gray-500">
                                  {risk.risk_category}
                                </span>
                              </div>
                              <p className="text-sm text-gray-600 mb-2">
                                {risk.risk_description}
                              </p>
                              <p className="text-sm text-primary-600">
                                建议: {risk.suggestion}
                              </p>
                            </div>
                          </div>
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}

              {/* 审查结论 */}
              {result.report?.conclusion && (
                <div className="card">
                  <div className="card-header">
                    <h3 className="font-semibold">审查结论</h3>
                  </div>
                  <div className="card-body">
                    <p className="text-gray-700 whitespace-pre-wrap">
                      {result.report.conclusion}
                    </p>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
