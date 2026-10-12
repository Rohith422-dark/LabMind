import { useEffect, type ReactNode } from "react";
import { Navigate } from "react-router-dom";
import { toast } from "sonner";
import { useAuth } from "@/context/AuthContext";

export function ProtectedRoute({ permission, children }: { permission?: string; children: ReactNode }) {
  const { me, loading, can } = useAuth();
  const denied = !!me && !!permission && !can(permission);

  useEffect(() => {
    if (denied) toast.error("You don't have access to that page");
  }, [denied]);

  if (loading) return <div className="p-8 text-slate-500">Loading…</div>;
  if (!me) return <Navigate to="/login" replace />;
  if (denied) return <Navigate to="/" replace />;
  return <>{children}</>;
}
