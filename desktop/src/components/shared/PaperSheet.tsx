import type { ReactNode } from 'react';
import { motion } from 'framer-motion';

interface PaperSheetProps {
  children: ReactNode;
  isActive?: boolean;
  className?: string;
}

export function PaperSheet({ children, isActive = true, className = '' }: PaperSheetProps) {
  return (
    <motion.div
      className={`
        notation-paper
        max-w-[800px] min-h-[400px]
        mx-auto
        ${isActive ? '' : 'opacity-60 scale-[0.98]'}
        ${className}
      `}
      initial={isActive ? { y: 20, opacity: 0 } : false}
      animate={isActive ? { y: 0, opacity: isActive ? 1 : 0.6 } : false}
      transition={{ duration: 0.4, ease: 'easeOut' }}
    >
      {children}
    </motion.div>
  );
}
