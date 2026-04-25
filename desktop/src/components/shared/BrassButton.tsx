import type { ReactNode } from 'react';
import { motion } from 'framer-motion';

interface BrassButtonProps {
  children: ReactNode;
  onClick?: () => void;
  size?: number;
  className?: string;
  disabled?: boolean;
  active?: boolean;
  variant?: 'circle' | 'square' | 'primary';
}

export function BrassButton({ children, onClick, size = 36, className = '', disabled = false, active = false, variant = 'circle' }: BrassButtonProps) {
  if (variant === 'primary') {
    return (
      <motion.button
        onClick={onClick}
        disabled={disabled}
        className={`btn-primary px-5 py-2.5 ${className}`}
        whileTap={disabled ? {} : { scale: 0.98 }}
      >
        {children}
      </motion.button>
    );
  }

  const isCircle = variant === 'circle';
  
  return (
    <motion.button
      onClick={onClick}
      disabled={disabled}
      className={`
        flex items-center justify-center
        ${isCircle ? 'rounded-full' : 'rounded-lg'}
        ${active 
          ? 'bg-[#2C2C2E] text-white' 
          : 'bg-white text-[#1C1C1E] border border-[#E5E5EA]'
        }
        cursor-pointer
        disabled:opacity-40 disabled:cursor-not-allowed
        transition-colors duration-150
        ${className}
      `}
      style={{ width: size, height: size }}
      whileHover={disabled ? {} : { backgroundColor: active ? '#1C1C1E' : '#F5F5F7' }}
      whileTap={disabled ? {} : { scale: 0.95 }}
    >
      {children}
    </motion.button>
  );
}
