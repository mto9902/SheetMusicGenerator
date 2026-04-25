import { useState, useRef, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { ChevronDown } from 'lucide-react';

interface DropdownProps<T extends string> {
  value: T;
  options: T[];
  onChange: (value: T) => void;
  label?: string;
}

export function Dropdown<T extends string>({ value, options, onChange, label }: DropdownProps<T>) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    if (open) {
      document.addEventListener('mousedown', handleClickOutside);
    }
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [open]);

  return (
    <div className="relative w-full" ref={containerRef}>
      {label && (
        <label className="block text-xs text-[#8E8E93] mb-1.5 font-medium">
          {label}
        </label>
      )}
      <button
        type="button"
        className="w-full h-10 px-3 flex items-center justify-between rounded-lg bg-white border border-[#E5E5EA] text-left text-sm text-[#1C1C1E] cursor-pointer transition-colors duration-150 hover:border-[#D1D1D6]"
        onClick={() => setOpen(!open)}
      >
        <span className="font-medium">{value}</span>
        <motion.div animate={{ rotate: open ? 180 : 0 }} transition={{ duration: 0.2 }}>
          <ChevronDown size={16} className="text-[#8E8E93]" />
        </motion.div>
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            className="absolute top-full left-0 right-0 mt-1 z-50 dropdown-menu"
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.15 }}
          >
            {options.map((opt) => (
              <button
                type="button"
                key={opt}
                className={`w-full text-left dropdown-option ${opt === value ? 'active' : ''}`}
                onClick={() => {
                  onChange(opt);
                  setOpen(false);
                }}
              >
                {opt}
              </button>
            ))}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
