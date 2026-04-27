import { NavLink } from "react-router-dom";
import { Music, Settings, Play, Pause, SkipBack, SkipForward } from "lucide-react";
import { motion } from "framer-motion";

interface ChromeBarProps {
  audioUrl?: string | null;
  isPlaying?: boolean;
  onPlayPause?: () => void;
}

const navItems = [
  { to: "/", label: "Compose" },
  { to: "/library", label: "History" },
  { to: "/settings", label: "Settings" },
];

export function ChromeBar({ audioUrl, isPlaying, onPlayPause }: ChromeBarProps) {
  return (
    <div className="top-bar h-[60px] flex items-center justify-between px-6 shrink-0 z-30">
      {/* Left - Brand */}
      <div className="flex items-center gap-2 min-w-0">
        <Music size={18} className="text-gray-500 shrink-0" strokeWidth={1.5} />
        <span 
          className="text-lg font-bold text-gray-800 tracking-tight truncate"
        >
          Caprice
        </span>
      </div>

      {/* Center - Transport or Navigation */}
      <div className="flex items-center gap-2">
        {audioUrl ? (
          <div className="flex items-center gap-2">
            <motion.button
              type="button"
              className="tactile-circle text-gray-600"
              style={{ width: 36, height: 36 }}
              whileTap={{ scale: 0.95 }}
              onClick={() => {}}
            >
              <SkipBack size={16} />
            </motion.button>
            <motion.button
              type="button"
              className={`flex items-center justify-center rounded-full cursor-pointer transition-colors duration-150 ${
                isPlaying
                  ? 'bg-[#3A3A3A] text-white shadow-inner'
                  : 'tactile-circle text-gray-600'
              }`}
              style={{ width: 40, height: 40 }}
              whileTap={{ scale: 0.95 }}
              onClick={onPlayPause}
            >
              {isPlaying ? (
                <Pause size={18} />
              ) : (
                <Play size={18} className="ml-0.5" />
              )}
            </motion.button>
            <motion.button
              type="button"
              className="tactile-circle text-gray-600"
              style={{ width: 36, height: 36 }}
              whileTap={{ scale: 0.95 }}
              onClick={() => {}}
            >
              <SkipForward size={16} />
            </motion.button>
          </div>
        ) : (
          <nav className="flex items-center gap-1 bg-white/70 rounded-2xl p-1 shadow-sm border border-black/5">
            {navItems.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.to === "/"}
                className={({ isActive }) =>
                  `px-4 py-1.5 rounded-xl text-sm font-semibold transition-colors ${
                    isActive
                      ? 'bg-white text-gray-900 shadow-sm'
                      : 'text-gray-500 hover:text-gray-900'
                  }`
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
        )}
      </div>

      {/* Right - Settings */}
      <div className="flex items-center gap-4 min-w-0">
        <NavLink 
          to="/settings" 
          className="text-gray-500 hover:text-gray-900 transition-colors shrink-0"
        >
          <Settings size={20} />
        </NavLink>
      </div>
    </div>
  );
}
