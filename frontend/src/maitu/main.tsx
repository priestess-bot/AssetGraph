import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import MaituApp from "./MaituApp";
import "../workbench/workbench.css";
import "./maitu.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, staleTime: 1000 },
    mutations: { retry: false },
  },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode><QueryClientProvider client={queryClient}><MaituApp /></QueryClientProvider></StrictMode>,
);
