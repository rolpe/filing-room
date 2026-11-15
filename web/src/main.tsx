import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

function App() {
  return <p style={{ padding: 24 }}>filing-room</p>;
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
