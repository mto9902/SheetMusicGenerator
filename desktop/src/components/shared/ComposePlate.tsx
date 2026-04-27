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
      className="tactile-btn-dark px-10 py-3.5 text-sm font-semibold rounded-xl disabled:opacity-40 disabled:cursor-not-allowed"
      whileTap={disabled ? {} : { scale: 0.98 }}
      transition={{ duration: 0.1 }}
    >
      {label}
    </motion.button>
  );
}
