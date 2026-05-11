import { useState } from 'react'
import { CheckCircle2, XCircle, Clock, AlertTriangle, FileText } from 'lucide-react'
import { reviewApi, type ReviewListItem, type ReviewDecisionRequest } from '@/services/api'
import clsx from 'clsx'

export default function ReviewsPage() {
  const [reviews, setReviews] = useState<ReviewListItem[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [selectedReview, setSelectedReview] = useState<ReviewListItem | null>(null)
  const [decision, setDecision] = useState<ReviewDecisionRequest['decision'] | null>(null)
  const [reason, setReason] = useState('')

  // 加载审核列表
  useState(() => {
    reviewApi.list({ include_pending: true, limit: 20 })
      .then((res) => setReviews(res.data.items))
      .finally(() => setIsLoading(false))
  })

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'approved':
        return <CheckCircle2 className="w-4 h-4 text-success-500" />
      case 'rejected':
        return <XCircle className="w-4 h-4 text-danger-500" />
      case 'pending':
      case 'in_review':
        return <Clock className="w-4 h-4 text-warning-500" />
      default:
        return <AlertTriangle className="w-4 h-4 text-gray-400" />
    }
  }

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'approved':
        return 'bg-success-50 text-success-700'
      case 'rejected':
        return 'bg-danger-50 text-danger-700'
      case 'pending':
      case 'in_review':
        return 'bg-warning-50 text-warning-700'
      default:
        return 'bg-gray-50 text-gray-700'
    }
  }

  const handleDecision = async (reviewId: string) => {
    if (!decision) return

    await reviewApi.decision(reviewId, {
      decision,
      reason: reason || undefined,
    })

    // 刷新列表
    const res = await reviewApi.list({ include_pending: true, limit: 20 })
    setReviews(res.data.items)
    setSelectedReview(null)
    setDecision(null)
    setReason('')
  }

  return (
    <div className="h-full flex flex-col">
      {/* 头部 */}
      <div className="px-6 py-4 border-b border-gray-200 bg-white">
        <h1 className="text-xl font-semibold text-gray-900">人工复核</h1>
        <p className="text-sm text-gray-500 mt-1">
          高风险任务人工审核，确保业务安全合规
        </p>
      </div>

      <div className="flex-1 flex overflow-hidden">
        {/* 列表 */}
        <div className="w-1/3 border-r border-gray-200 overflow-y-auto">
          <div className="p-4 space-y-2">
            {isLoading ? (
              <div className="text-center py-8 text-gray-500">加载中...</div>
            ) : reviews.length === 0 ? (
              <div className="text-center py-8 text-gray-500">暂无待审核任务</div>
            ) : (
              reviews.map((review) => (
                <div
                  key={review.review_id}
                  onClick={() => setSelectedReview(review)}
                  className={clsx(
                    'p-4 rounded-lg border cursor-pointer transition-all',
                    selectedReview?.review_id === review.review_id
                      ? 'border-primary-500 bg-primary-50'
                      : 'border-gray-200 hover:border-gray-300 hover:bg-gray-50'
                  )}
                >
                  <div className="flex items-center justify-between mb-2">
                    <span className={clsx('px-2 py-0.5 rounded text-xs font-medium', getStatusColor(review.status))}>
                      {review.status === 'pending' && '待审核'}
                      {review.status === 'in_review' && '审核中'}
                      {review.status === 'approved' && '已通过'}
                      {review.status === 'rejected' && '已拒绝'}
                    </span>
                    <span className="text-xs text-gray-500">
                      {new Date(review.submitted_at).toLocaleString()}
                    </span>
                  </div>
                  <h3 className="font-medium text-gray-900 mb-1">{review.title}</h3>
                  <p className="text-sm text-gray-500 line-clamp-2">{review.description}</p>
                  <div className="flex items-center gap-2 mt-2">
                    <span className={clsx(
                      'px-2 py-0.5 rounded text-xs',
                      review.risk_level === 'high' || review.risk_level === 'critical'
                        ? 'bg-danger-50 text-danger-600'
                        : 'bg-gray-100 text-gray-600'
                    )}>
                      {review.risk_level === 'low' && '低风险'}
                      {review.risk_level === 'medium' && '中风险'}
                      {review.risk_level === 'high' && '高风险'}
                      {review.risk_level === 'critical' && '严重风险'}
                    </span>
                    <span className="text-xs text-gray-400">{review.task_type}</span>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>

        {/* 详情 */}
        <div className="flex-1 overflow-y-auto p-6">
          {selectedReview ? (
            <div className="max-w-2xl">
              <div className="card">
                <div className="card-header flex items-center justify-between">
                  <h2 className="text-lg font-semibold">{selectedReview.title}</h2>
                  {getStatusIcon(selectedReview.status)}
                </div>
                <div className="card-body space-y-4">
                  <div>
                    <h4 className="text-sm font-medium text-gray-700 mb-1">任务类型</h4>
                    <p className="text-gray-900">{selectedReview.task_type}</p>
                  </div>
                  <div>
                    <h4 className="text-sm font-medium text-gray-700 mb-1">风险等级</h4>
                    <p className={clsx(
                      selectedReview.risk_level === 'high' || selectedReview.risk_level === 'critical'
                        ? 'text-danger-600 font-medium'
                        : 'text-gray-900'
                    )}>
                      {selectedReview.risk_level === 'low' && '低风险'}
                      {selectedReview.risk_level === 'medium' && '中风险'}
                      {selectedReview.risk_level === 'high' && '高风险'}
                      {selectedReview.risk_level === 'critical' && '严重风险'}
                    </p>
                  </div>
                  <div>
                    <h4 className="text-sm font-medium text-gray-700 mb-1">详细描述</h4>
                    <p className="text-gray-900">{selectedReview.description}</p>
                  </div>
                  <div>
                    <h4 className="text-sm font-medium text-gray-700 mb-1">提交时间</h4>
                    <p className="text-gray-600">{new Date(selectedReview.submitted_at).toLocaleString()}</p>
                  </div>
                </div>
              </div>

              {/* 审核操作 */}
              {(selectedReview.status === 'pending' || selectedReview.status === 'in_review') && (
                <div className="card mt-6">
                  <div className="card-header">
                    <h3 className="font-semibold">审核决策</h3>
                  </div>
                  <div className="card-body space-y-4">
                    <div className="flex gap-2">
                      <button
                        onClick={() => setDecision('approve')}
                        className={clsx(
                          'flex-1 py-2 px-4 rounded-lg border-2 transition-all',
                          decision === 'approve'
                            ? 'border-success-500 bg-success-50 text-success-700'
                            : 'border-gray-200 hover:border-gray-300'
                        )}
                      >
                        <CheckCircle2 className="w-5 h-5 mx-auto mb-1" />
                        <span className="text-sm font-medium">通过</span>
                      </button>
                      <button
                        onClick={() => setDecision('revise')}
                        className={clsx(
                          'flex-1 py-2 px-4 rounded-lg border-2 transition-all',
                          decision === 'revise'
                            ? 'border-warning-500 bg-warning-50 text-warning-700'
                            : 'border-gray-200 hover:border-gray-300'
                        )}
                      >
                        <AlertTriangle className="w-5 h-5 mx-auto mb-1" />
                        <span className="text-sm font-medium">要求修改</span>
                      </button>
                      <button
                        onClick={() => setDecision('reject')}
                        className={clsx(
                          'flex-1 py-2 px-4 rounded-lg border-2 transition-all',
                          decision === 'reject'
                            ? 'border-danger-500 bg-danger-50 text-danger-700'
                            : 'border-gray-200 hover:border-gray-300'
                        )}
                      >
                        <XCircle className="w-5 h-5 mx-auto mb-1" />
                        <span className="text-sm font-medium">拒绝</span>
                      </button>
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-2">
                        决策理由（可选）
                      </label>
                      <textarea
                        value={reason}
                        onChange={(e) => setReason(e.target.value)}
                        placeholder="请输入决策理由..."
                        className="textarea"
                        rows={3}
                      />
                    </div>
                    <button
                      onClick={() => handleDecision(selectedReview.review_id)}
                      disabled={!decision}
                      className="btn-primary w-full disabled:opacity-50"
                    >
                      提交决策
                    </button>
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="h-full flex items-center justify-center text-gray-500">
              <div className="text-center">
                <FileText className="w-16 h-16 mx-auto mb-4 text-gray-300" />
                <p>选择一条审核任务查看详情</p>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
