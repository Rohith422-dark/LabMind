import { Link } from "react-router-dom";

export default function NotFound() {
  return (
    <div className="card mx-auto mt-16 max-w-md p-8 text-center">
      <h1 className="text-xl font-semibold">Page not found</h1>
      <Link to="/" className="btn-primary mt-4">Back to dashboard</Link>
    </div>
  );
}
