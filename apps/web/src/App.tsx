import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import Layout from './components/Layout'
import HomePage from './pages/HomePage'
import ChatPage from './pages/ChatPage'
import AnalyticsPage from './pages/AnalyticsPage'
import ContractPage from './pages/ContractPage'
import ReviewsPage from './pages/ReviewsPage'
import KnowledgePage from './pages/KnowledgePage'

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Layout />}>
          <Route index element={<HomePage />} />
          <Route path="chat" element={<ChatPage />} />
          <Route path="chat/:conversationId" element={<ChatPage />} />
          <Route path="analytics" element={<AnalyticsPage />} />
          <Route path="contract" element={<ContractPage />} />
          <Route path="reviews" element={<ReviewsPage />} />
          <Route path="knowledge" element={<KnowledgePage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}

export default App
