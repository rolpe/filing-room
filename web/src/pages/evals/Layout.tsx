import { NavLink, Outlet } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../../lib/api";
import { ErrorState, SkeletonRows } from "../../components/States";
import "../../styles/company.css";
import "../../styles/evals.css";

export function EvalsLayout() {
  const cov = useQuery({ queryKey: ["coverage"], queryFn: api.coverage });
  if (cov.isLoading) return <div className="page-body"><SkeletonRows rows={4} cols={4} /></div>;
  if (!cov.data?.dev_tools) return <ErrorState title="Page not found" error="There's nothing at this address." />;
  return (
    <>
      <div className="page-head ev-head">
        <h1>Evaluation</h1>
        <span className="count">How the answering engine is measured: answers graded against an answer key</span>
      </div>
      <nav className="tabs" aria-label="Evaluation sections">
        <NavLink to="/evals" end>Runs</NavLink>
        <NavLink to="/evals/golden">Golden set</NavLink>
        <NavLink to="/evals/run">Run an eval</NavLink>
      </nav>
      <Outlet />
    </>
  );
}
