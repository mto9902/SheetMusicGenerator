import { NavLink, Navigate, Route, Routes } from "react-router-dom";

import { API_BASE } from "@/lib/api";
import { CreatePage } from "@/pages/CreatePage";
import { ExercisePage } from "@/pages/ExercisePage";
import { HomePage } from "@/pages/HomePage";
import { LibraryPage } from "@/pages/LibraryPage";
import { SettingsPage } from "@/pages/SettingsPage";

const navItems = [
  { to: "/", label: "Home", detail: "Dashboard and recent work" },
  { to: "/create", label: "Create", detail: "Generate a new reading rep" },
  { to: "/library", label: "Library", detail: "Presets, sheets, and sessions" },
  { to: "/settings", label: "Settings", detail: "Desktop defaults" },
];

export default function App() {
  return (
    <div className="shell">
      <aside className="shell__sidebar">
        <div className="shell__brand">
          <p className="eyebrow">SheetGenerator</p>
          <h1>Desktop-first sight reading</h1>
          <p>
            Browser release surface now, Tauri-ready structure later. The Python generator stays
            remote behind the same API contract.
          </p>
        </div>

        <nav className="shell__nav">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/"}
              className={({ isActive }) => `shell__link ${isActive ? "shell__link--active" : ""}`}
            >
              <strong>{item.label}</strong>
              <span>{item.detail}</span>
            </NavLink>
          ))}
        </nav>

        <div className="shell__meta">
          <span>Generator API</span>
          <strong>{API_BASE}</strong>
        </div>
      </aside>

      <main className="shell__content">
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/create" element={<CreatePage />} />
          <Route path="/library" element={<LibraryPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/exercise/:id" element={<ExercisePage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  );
}
