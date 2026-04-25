import { NavLink, Navigate, Route, Routes } from "react-router-dom";

import { API_BASE } from "@/lib/api";
import { CreatePage } from "@/pages/CreatePage";
import { ExercisePage } from "@/pages/ExercisePage";
import { LibraryPage } from "@/pages/LibraryPage";
import { SettingsPage } from "@/pages/SettingsPage";

const navItems = [
  { to: "/", label: "Compose" },
  { to: "/library", label: "History" },
  { to: "/settings", label: "Settings" },
];

export default function App() {
  const apiHost = API_BASE.replace(/^https?:\/\//, "");

  return (
    <div className="app-shell">
      <header className="studio-topbar">
        <div className="studio-topbar__brand" aria-label="SheetGenerator desktop">
          <span className="studio-topbar__mark">SG</span>
          <div>
            <strong>Caprice</strong>
            <span>Sight-reading composer</span>
          </div>
        </div>

        <nav className="studio-topbar__nav" aria-label="Primary navigation">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/"}
              className={({ isActive }) =>
                `studio-topbar__link ${isActive ? "studio-topbar__link--active" : ""}`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>

        <div className="studio-topbar__api" title={API_BASE}>
          <span>API</span>
          <strong>{apiHost}</strong>
        </div>
      </header>

      <main className="app-shell__content">
        <Routes>
          <Route path="/" element={<CreatePage />} />
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
