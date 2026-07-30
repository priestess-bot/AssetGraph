import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import ConsoleApp from "./ConsoleApp";
import { ConsoleErrorBoundary } from "./ErrorBoundary";
import "../workbench/workbench.css";
import "./console.css";
import "../product/product.css";


const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, staleTime: 1_000 },
    mutations: { retry: false },
  },
});

document.getElementById("console-boot-fallback")?.remove();

createRoot(document.getElementById("root")!).render(
  <StrictMode><ConsoleErrorBoundary><QueryClientProvider client={queryClient}><ConsoleApp /></QueryClientProvider></ConsoleErrorBoundary></StrictMode>,
);
