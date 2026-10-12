import { useAuth } from "@/context/AuthContext";

export default function Dashboard() {
  const { me } = useAuth();
  return (
    <div>
      <h1 className="text-2xl font-bold">Welcome, {me?.user.full_name}</h1>
      <div className="card mt-6 p-8 text-slate-500">
        No activity to show yet. Counts appear here once real records exist.
      </div>
    </div>
  );
}
