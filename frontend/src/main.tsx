import React from "react";
import ReactDOM from "react-dom/client";
import SignIn from "./screens/SignIn";
import "./styles/tokens.css";
import "./styles/app.css";
import "./styles/journey.css";
import "./styles/motion.css";
import "./styles/legibility.css";
// Firebase's Google sign-in only trusts localhost (its default authorized domain), and Vite prints 127.0.0.1.
if (location.hostname === "127.0.0.1") location.replace(location.href.replace("//127.0.0.1", "//localhost"));
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <SignIn />
  </React.StrictMode>,
);
