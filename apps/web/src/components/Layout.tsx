import { Outlet, Link, useLocation } from 'react-router-dom'
import {
  MessageSquare,
  BarChart3,
  FileText,
  CheckSquare,
  BookOpen,
  Home,
  LogOut,
  User,
} from 'lucide-react'
import clsx from 'clsx'

const navigation = [
  { name: '首页', href: '/', icon: Home },
  { name: '智能问答', href: '/chat', icon: MessageSquare },
  { name: '经营分析', href: '/analytics', icon: BarChart3 },
  { name: '合同审查', href: '/contract', icon: FileText },
  { name: '人工复核', href: '/reviews', icon: CheckSquare },
  { name: '知识库', href: '/knowledge', icon: BookOpen },
]

export default function Layout() {
  const location = useLocation()

  return (
    <div className="min-h-screen flex">
      {/* 侧边栏 */}
      <aside className="w-64 bg-white border-r border-gray-200 flex flex-col">
        {/* Logo */}
        <div className="h-16 flex items-center px-6 border-b border-gray-200">
          <h1 className="text-lg font-bold text-gray-900">企业知识平台</h1>
        </div>

        {/* 导航 */}
        <nav className="flex-1 px-4 py-4 space-y-1">
          {navigation.map((item) => {
            const isActive = location.pathname === item.href ||
              (item.href !== '/' && location.pathname.startsWith(item.href))

            return (
              <Link
                key={item.name}
                to={item.href}
                className={clsx(
                  'flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors',
                  isActive
                    ? 'bg-primary-50 text-primary-700'
                    : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900'
                )}
              >
                <item.icon className="w-5 h-5" />
                {item.name}
              </Link>
            )
          })}
        </nav>

        {/* 用户信息 */}
        <div className="p-4 border-t border-gray-200">
          <div className="flex items-center gap-3 px-3 py-2">
            <div className="w-8 h-8 rounded-full bg-primary-100 flex items-center justify-center">
              <User className="w-4 h-4 text-primary-600" />
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-gray-900 truncate">用户</p>
              <p className="text-xs text-gray-500 truncate">admin@company.com</p>
            </div>
            <button className="p-1.5 rounded-lg hover:bg-gray-100">
              <LogOut className="w-4 h-4 text-gray-400" />
            </button>
          </div>
        </div>
      </aside>

      {/* 主内容区 */}
      <main className="flex-1 overflow-auto">
        <Outlet />
      </main>
    </div>
  )
}
