import { motion } from 'framer-motion';

interface ComposePlateProps {
  onClick: () => void;
  disabled?: boolean;
  label?: string;
}

export function ComposePlate({ onClick, disabled, label = 'Compose' }: ComposePlateProps) {
  return (
    <motion.button
      onClick={onClick}
      disabled={disabled}
      className="btn-primary px-8 py-3 text-sm font-semibold disabled:opacity-40 disabled:cursor-not-allowed"
      whileTap={disabled ? {} : { scale: 0.98 }}
      transition={{ duration: 0.1 }}
    >
      {label}
    </motion.button>
  );
}
