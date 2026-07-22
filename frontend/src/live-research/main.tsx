import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import LiveResearchApp from "./LiveResearchApp";
import "../workbench/workbench.css";
import "./live-research.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, staleTime: 1000 },
    mutations: { retry: false },
  },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode><QueryClientProvider client={queryClient}><LiveResearchApp /></QueryClientProvider></StrictMode>,
);
