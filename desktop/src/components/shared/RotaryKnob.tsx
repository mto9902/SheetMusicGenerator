import { useRef, useCallback } from 'react';
import { motion } from 'framer-motion';

interface RotaryKnobProps {
  value: number;
  min: number;
  max: number;
  size?: number;
  onChange: (value: number) => void;
  label?: string;
}

export function RotaryKnob({ value, min, max, size = 56, onChange, label }: RotaryKnobProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  
  const normalized = (value - min) / (max - min);
  const rotation = -135 + normalized * 270;
  
  const handlePointerMove = useCallback((e: PointerEvent) => {
    if (!containerRef.current) return;
    const rect = containerRef.current.getBoundingClientRect();
    const centerX = rect.left + rect.width / 2;
    const centerY = rect.top + rect.height / 2;
    const dx = e.clientX - centerX;
    const dy = e.clientY - centerY;
    const angle = Math.atan2(dy, dx) * (180 / Math.PI);
    let mapped = ((angle + 135) / 270) * (max - min) + min;
    mapped = Math.max(min, Math.min(max, mapped));
    onChange(Math.round(mapped));
  }, [min, max, onChange]);

  const handlePointerDown = () => {
    window.addEventListener('pointermove', handlePointerMove);
    window.addEventListener('pointerup', () => {
      window.removeEventListener('pointermove', handlePointerMove);
    }, { once: true });
  };

  return (
    <div className="flex flex-col items-center gap-1.5">
      <div
        ref={containerRef}
        className="knob-clean relative select-none"
        style={{ width: size, height: size }}
        onPointerDown={handlePointerDown}
      >
        <motion.div
          className="absolute inset-0 flex items-start justify-center pt-[12%]"
          animate={{ rotate: rotation }}
          transition={{ duration: 0.1, ease: 'easeOut' }}
          style={{ originX: 0.5, originY: 0.5 }}
        >
          <div className="w-[2px] h-[35%] bg-[#2C2C2E] rounded-full" />
        </motion.div>
      </div>
      {label && (
        <span className="text-xs text-[#8E8E93]" style={{ fontFamily: '"SF Mono", Monaco, monospace' }}>
          {label}
        </span>
      )}
    </div>
  );
}
