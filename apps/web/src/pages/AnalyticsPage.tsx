import { useState } from 'react'
import { BarChart3, TrendingUp, Table, FileText, Loader2 } from 'lucide-react'
import { analyticsApi, type AnalyticsQueryResponse } from '@/services/api'

export default function AnalyticsPage() {
  const [query, setQuery] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [result, setResult] = useState<AnalyticsQueryResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!query.trim()) return

    setIsLoading(true)
    setError(null)
    setResult(null)

    try {
      const response = await analyticsApi.query({
        query: query.trim(),
        output_mode: 'standard',
      })
      setResult(response.data)
    } catch (err: any) {
      setError(err.response?.data?.message || '查询失败，请稍后重试')
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="h-full flex flex-col">
      {/* 头部 */}
      <div className="px-6 py-4 border-b border-gray-200 bg-white">
        <h1 className="text-xl font-semibold text-gray-900">经营分析</h1>
        <p className="text-sm text-gray-500 mt-1">
          使用自然语言查询经营数据，自动生成 SQL 和分析报告
        </p>
      </div>

      <div className="flex-1 overflow-auto p-6">
        {/* 查询表单 */}
        <div className="card mb-6">
          <div className="card-body">
            <form onSubmit={handleSubmit} className="flex gap-4">
              <input
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="例如：查询4月份各部门的销售收入"
                className="input flex-1"
                disabled={isLoading}
              />
              <button
                type="submit"
                disabled={!query.trim() || isLoading}
                className="btn-primary px-6 disabled:opacity-50"
              >
                {isLoading ? (
                  <Loader2 className="w-5 h-5 animate-spin" />
                ) : (
                  '查询'
                )}
              </button>
            </form>
          </div>
        </div>

        {/* 错误信息 */}
        {error && (
          <div className="card mb-6 border-danger-500">
            <div className="card-body text-danger-600">
              {error}
            </div>
          </div>
        )}

        {/* 结果展示 */}
        {result?.result && (
          <div className="space-y-6">
            {/* SQL 语句 */}
            {result.result.sql && (
              <div className="card">
                <div className="card-header flex items-center gap-2">
                  <Table className="w-5 h-5 text-primary-600" />
                  <h3 className="font-semibold">生成的 SQL</h3>
                </div>
                <div className="card-body">
                  <pre className="bg-gray-900 text-gray-100 p-4 rounded-lg overflow-x-auto text-sm font-mono">
                    {result.result.sql}
                  </pre>
                </div>
              </div>
            )}

            {/* 数据表格 */}
            {result.result.data && result.result.data.length > 0 && (
              <div className="card">
                <div className="card-header flex items-center gap-2">
                  <BarChart3 className="w-5 h-5 text-primary-600" />
                  <h3 className="font-semibold">查询结果</h3>
                </div>
                <div className="card-body overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-gray-200">
                        {Object.keys(result.result.data[0]).map((key) => (
                          <th key={key} className="px-4 py-2 text-left font-medium text-gray-700">
                            {key}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {result.result.data.map((row, i) => (
                        <tr key={i} className="border-b border-gray-100 hover:bg-gray-50">
                          {Object.values(row).map((val, j) => (
                            <td key={j} className="px-4 py-2 text-gray-600">
                              {String(val)}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {/* 分析总结 */}
            {result.result.summary && (
              <div className="card">
                <div className="card-header flex items-center gap-2">
                  <TrendingUp className="w-5 h-5 text-primary-600" />
                  <h3 className="font-semibold">分析总结</h3>
                </div>
                <div className="card-body">
                  <p className="text-gray-700 whitespace-pre-wrap">
                    {result.result.summary}
                  </p>
                </div>
              </div>
            )}
          </div>
        )}

        {/* 空状态 */}
        {!result && !error && !isLoading && (
          <div className="flex flex-col items-center justify-center h-64 text-center">
            <BarChart3 className="w-16 h-16 text-gray-300 mb-4" />
            <h3 className="text-lg font-medium text-gray-700 mb-2">
              开始查询
            </h3>
            <p className="text-gray-500 max-w-md">
              输入您想要查询的经营数据问题，系统会自动分析并生成 SQL 查询
            </p>
          </div>
        )}
      </div>
    </div>
  )
}
