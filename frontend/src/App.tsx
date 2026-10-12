import { Route, Routes } from "react-router-dom";
import { Layout } from "@/components/Layout";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import Login from "@/pages/Login";
import Dashboard from "@/pages/Dashboard";
import AuditLog from "@/pages/AuditLog";
import AdminUsers from "@/pages/AdminUsers";
import NotFound from "@/pages/NotFound";

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route element={<ProtectedRoute><Layout /></ProtectedRoute>}>
        <Route index element={<Dashboard />} />
        <Route path="audit" element={<ProtectedRoute permission="audit.view"><AuditLog /></ProtectedRoute>} />
        <Route path="admin/users" element={<ProtectedRoute permission="users.manage"><AdminUsers /></ProtectedRoute>} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}
