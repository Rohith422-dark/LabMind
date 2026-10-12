import { Route, Routes } from "react-router-dom";
import { Layout } from "@/components/Layout";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import Login from "@/pages/Login";
import Dashboard from "@/pages/Dashboard";
import ChatAssistant from "@/pages/ChatAssistant";
import SopLibrary from "@/pages/SopLibrary";
import SopViewer from "@/pages/SopViewer";
import Troubleshooting from "@/pages/Troubleshooting";
import Inventory from "@/pages/Inventory";
import MyRequests from "@/pages/MyRequests";
import AnalystConsole from "@/pages/AnalystConsole";
import SopManagement from "@/pages/SopManagement";
import KnowledgeGaps from "@/pages/KnowledgeGaps";
import Calculators from "@/pages/Calculators";
import AuditLog from "@/pages/AuditLog";
import AdminUsers from "@/pages/AdminUsers";
import NotFound from "@/pages/NotFound";
import type { ReactNode } from "react";

const guard = (permission: string, el: ReactNode) => <ProtectedRoute permission={permission}>{el}</ProtectedRoute>;

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route element={<ProtectedRoute><Layout /></ProtectedRoute>}>
        <Route index element={<Dashboard />} />
        <Route path="chat" element={guard("knowledge.use", <ChatAssistant />)} />
        <Route path="sops" element={guard("knowledge.use", <SopLibrary />)} />
        <Route path="sops/:id" element={guard("knowledge.use", <SopViewer />)} />
        <Route path="troubleshoot" element={guard("knowledge.use", <Troubleshooting />)} />
        <Route path="inventory" element={guard("inventory.view", <Inventory />)} />
        <Route path="my-requests" element={guard("requests.create", <MyRequests />)} />
        <Route path="calculators" element={guard("calculators.use", <Calculators />)} />
        <Route path="analyst" element={guard("inventory.manage", <AnalystConsole />)} />
        <Route path="sop-management" element={guard("sop.manage", <SopManagement />)} />
        <Route path="gaps" element={guard("gaps.view", <KnowledgeGaps />)} />
        <Route path="audit" element={guard("audit.view", <AuditLog />)} />
        <Route path="admin/users" element={guard("users.manage", <AdminUsers />)} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}
