import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createBrowserRouter, Navigate, RouterProvider } from "react-router-dom";
import { Shell } from "./components/Shell";
import { CoveragePage } from "./pages/Coverage";
import { CompanyPage } from "./pages/Company";
import { FindingsPage } from "./pages/Findings";
import { OverviewPage } from "./pages/Overview";
import { MemoPage } from "./pages/Memo";
import { QAPage } from "./pages/QA";
import { FilingsPage } from "./pages/Filings";
import { UsagePage } from "./pages/Usage";
import { EvalsLayout } from "./pages/evals/Layout";
import { EvalRunsPage } from "./pages/evals/Runs";
import { EvalRunPage } from "./pages/evals/RunDetail";
import { GoldenPage } from "./pages/evals/Golden";
import { RunEvalPage } from "./pages/evals/RunEval";
import { ErrorState } from "./components/States";
import "./styles/tokens.css";
import "./styles/app.css";

const qc = new QueryClient({
  defaultOptions: { queries: { staleTime: 15_000, refetchOnWindowFocus: false, retry: 1 } },
});

const router = createBrowserRouter([
  {
    path: "/",
    element: <Shell />,
    errorElement: <ErrorState title="This page couldn't be shown" error="Reload the page, or go back to coverage." />,
    children: [
      { index: true, element: <CoveragePage /> },
      {
        path: "c/:ticker",
        element: <CompanyPage />,
        children: [
          { index: true, element: <Navigate to="findings" replace /> },
          { path: "overview", element: <OverviewPage /> },
          { path: "findings", element: <FindingsPage /> },
          { path: "memo", element: <MemoPage /> },
          { path: "qa", element: <QAPage /> },
          { path: "filings", element: <FilingsPage /> },
        ],
      },
      { path: "usage", element: <UsagePage /> },
      {
        path: "evals",
        element: <EvalsLayout />,
        children: [
          { index: true, element: <EvalRunsPage /> },
          { path: "runs/:kind/:name", element: <EvalRunPage /> },
          { path: "golden", element: <GoldenPage /> },
          { path: "run", element: <RunEvalPage /> },
        ],
      },
      { path: "*", element: <ErrorState title="Page not found" error="There's nothing at this address." /> },
    ],
  },
]);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={qc}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
);
