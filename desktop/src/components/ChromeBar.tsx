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
    <div className="top-bar h-[52px] flex items-center justify-between px-6 shrink-0 z-30">
      {/* Left - Brand */}
      <div className="flex items-center gap-2 min-w-0">
        <Music size={18} className="text-[#8E8E93] shrink-0" strokeWidth={1.5} />
        <span 
          className="text-lg font-bold text-[#1C1C1E] tracking-tight truncate"
          style={{ fontFamily: 'Inter, sans-serif' }}
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
              className="flex items-center justify-center rounded-full bg-white text-[#1C1C1E] border border-[#E5E5EA] cursor-pointer transition-colors duration-150 hover:bg-[#F5F5F7]"
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
                  ? 'bg-[#2C2C2E] text-white'
                  : 'bg-white text-[#1C1C1E] border border-[#E5E5EA] hover:bg-[#F5F5F7]'
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
              className="flex items-center justify-center rounded-full bg-white text-[#1C1C1E] border border-[#E5E5EA] cursor-pointer transition-colors duration-150 hover:bg-[#F5F5F7]"
              style={{ width: 36, height: 36 }}
              whileTap={{ scale: 0.95 }}
              onClick={() => {}}
            >
              <SkipForward size={16} />
            </motion.button>
          </div>
        ) : (
          <nav className="flex items-center gap-1 bg-[#F5F5F7] rounded-lg p-1">
            {navItems.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.to === "/"}
                className={({ isActive }) =>
                  `px-4 py-1.5 rounded-md text-sm font-medium transition-colors ${
                    isActive
                      ? 'bg-white text-[#1C1C1E] shadow-sm'
                      : 'text-[#8E8E93] hover:text-[#1C1C1E]'
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
          className="text-[#8E8E93] hover:text-[#1C1C1E] transition-colors shrink-0"
        >
          <Settings size={20} />
        </NavLink>
      </div>
    </div>
  );
}
