import React from "react";
import ReactDOM from "react-dom/client";
import SignIn from "./screens/SignIn";
import "./styles/tokens.css";
import "./styles/app.css";
import "./styles/journey.css";
import "./styles/motion.css";
import "./styles/legibility.css";
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <SignIn />
  </React.StrictMode>,
);
