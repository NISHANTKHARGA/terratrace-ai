import { Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import { EmptyState } from "./components/ui";
import AnalyzePage from "./pages/AnalyzePage";
import MapPage from "./pages/MapPage";
import ReportsPage from "./pages/ReportsPage";
import JobPage from "./pages/JobPage";
import AgentDetailPage from "./pages/AgentDetailPage";
import FindingDetailPage from "./pages/FindingDetailPage";

function NotFound() {
  return (
    <div className="p-6">
      <div className="panel">
        <EmptyState
          title="Page not found."
          hint="Use the navigation above to reach Analyze, Map or Reports."
        />
      </div>
    </div>
  );
}

export default function App() {
  return (
    <Layout>
      <Routes>
        {/* main experience */}
        <Route path="/" element={<AnalyzePage />} />
        <Route path="/map" element={<MapPage />} />
        <Route path="/reports" element={<ReportsPage />} />

        {/* detail views reached from the main experience */}
        <Route path="/jobs/:jobId" element={<JobPage />} />
        <Route path="/findings/:findingId" element={<FindingDetailPage />} />
        <Route path="/agents/:agentId" element={<AgentDetailPage />} />

        {/* legacy paths → simplified navigation */}
        <Route path="/analyze" element={<Navigate to="/" replace />} />
        <Route path="/history" element={<Navigate to="/reports" replace />} />
        <Route path="/findings" element={<Navigate to="/reports" replace />} />
        <Route path="/agents" element={<Navigate to="/reports" replace />} />
        <Route path="/data" element={<Navigate to="/reports" replace />} />
        <Route path="/models" element={<Navigate to="/reports" replace />} />
        <Route path="*" element={<NotFound />} />
      </Routes>
    </Layout>
  );
}
