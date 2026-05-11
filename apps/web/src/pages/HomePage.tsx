import { Link } from 'react-router-dom'
import {
  MessageSquare,
  BarChart3,
  FileText,
  CheckSquare,
  BookOpen,
  ArrowRight,
  TrendingUp,
  Clock,
} from 'lucide-react'

const features = [
  {
    name: '智能问答',
    description: '基于企业知识库的智能问答，涵盖制度政策、安全规程、设备检修等',
    href: '/chat',
    icon: MessageSquare,
    color: 'bg-blue-500',
  },
  {
    name: '经营分析',
    description: '自然语言查询经营数据，自动生成 SQL 和分析报告',
    href: '/analytics',
    icon: BarChart3,
    color: 'bg-green-500',
  },
  {
    name: '合同审查',
    description: '智能识别合同风险，生成专业审查报告',
    href: '/contract',
    icon: FileText,
    color: 'bg-purple-500',
  },
  {
    name: '人工复核',
    description: '高风险任务人工审核，确保业务安全合规',
    href: '/reviews',
    icon: CheckSquare,
    color: 'bg-orange-500',
  },
]

const stats = [
  { label: '知识库文档', value: '1,234', icon: BookOpen },
  { label: '问答次数', value: '5,678', icon: MessageSquare },
  { label: '分析报告', value: '890', icon: BarChart3 },
  { label: '合同审查', value: '456', icon: FileText },
]

const recentActivities = [
  {
    id: 1,
    type: 'chat',
    content: '用户咨询了安全生产相关问题',
    time: '2分钟前',
  },
  {
    id: 2,
    type: 'analytics',
    content: '生成了4月份经营分析报告',
    time: '15分钟前',
  },
  {
    id: 3,
    type: 'contract',
    content: '采购合同审查完成，发现2处中风险',
    time: '1小时前',
  },
  {
    id: 4,
    type: 'review',
    content: '1个合同审查待人工复核',
    time: '2小时前',
  },
]

export default function HomePage() {
  return (
    <div className="p-8">
      {/* 欢迎区域 */}
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-gray-900 mb-2">
          欢迎使用企业知识 Agent 平台
        </h1>
        <p className="text-gray-600">
          基于大语言模型的企业知识问答、经营分析和合同审查智能平台
        </p>
      </div>

      {/* 功能卡片 */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
        {features.map((feature) => (
          <Link
            key={feature.name}
            to={feature.href}
            className="group card p-6 hover:shadow-lg transition-shadow"
          >
            <div className="flex items-center gap-4 mb-4">
              <div className={`w-12 h-12 rounded-lg ${feature.color} flex items-center justify-center`}>
                <feature.icon className="w-6 h-6 text-white" />
              </div>
              <h3 className="text-lg font-semibold text-gray-900 group-hover:text-primary-600 transition-colors">
                {feature.name}
              </h3>
            </div>
            <p className="text-gray-600 text-sm mb-4">{feature.description}</p>
            <div className="flex items-center text-primary-600 text-sm font-medium">
              立即使用
              <ArrowRight className="w-4 h-4 ml-1 group-hover:translate-x-1 transition-transform" />
            </div>
          </Link>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* 统计信息 */}
        <div className="lg:col-span-2">
          <div className="card">
            <div className="card-header flex items-center justify-between">
              <h2 className="text-lg font-semibold text-gray-900">平台概览</h2>
              <div className="flex items-center text-sm text-gray-500">
                <Clock className="w-4 h-4 mr-1" />
                实时更新
              </div>
            </div>
            <div className="card-body">
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                {stats.map((stat) => (
                  <div key={stat.label} className="text-center p-4 bg-gray-50 rounded-lg">
                    <div className="w-10 h-10 rounded-full bg-primary-100 flex items-center justify-center mx-auto mb-2">
                      <stat.icon className="w-5 h-5 text-primary-600" />
                    </div>
                    <div className="text-2xl font-bold text-gray-900">{stat.value}</div>
                    <div className="text-sm text-gray-500">{stat.label}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>

        {/* 最近活动 */}
        <div>
          <div className="card">
            <div className="card-header">
              <h2 className="text-lg font-semibold text-gray-900">最近活动</h2>
            </div>
            <div className="card-body">
              <div className="space-y-4">
                {recentActivities.map((activity) => (
                  <div key={activity.id} className="flex items-start gap-3">
                    <div className="w-2 h-2 rounded-full bg-primary-500 mt-2" />
                    <div className="flex-1">
                      <p className="text-sm text-gray-900">{activity.content}</p>
                      <p className="text-xs text-gray-500 mt-1">{activity.time}</p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* 快捷入口 */}
      <div className="mt-8 card">
        <div className="card-header">
          <h2 className="text-lg font-semibold text-gray-900">快捷入口</h2>
        </div>
        <div className="card-body">
          <div className="flex flex-wrap gap-3">
            <Link
              to="/chat?quick=安全生产"
              className="btn-secondary"
            >
              安全生产咨询
            </Link>
            <Link
              to="/chat?quick=设备检修"
              className="btn-secondary"
            >
              设备检修指导
            </Link>
            <Link
              to="/analytics?quick=月度报表"
              className="btn-secondary"
            >
              月度经营报表
            </Link>
            <Link
              to="/contract"
              className="btn-secondary"
            >
              上传合同审查
            </Link>
          </div>
        </div>
      </div>
    </div>
  )
}
