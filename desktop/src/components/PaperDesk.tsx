import { motion } from 'framer-motion';
import { Music } from 'lucide-react';
import { NotationPanel } from './NotationPanel';
import { ComposePlate } from './shared/ComposePlate';
import type { StoredExercise } from '@shared/types';

interface PaperDeskProps {
  exercise: StoredExercise | null;
  scale?: number;
  onCompose: () => void;
  submitting?: boolean;
}

export function PaperDesk({ exercise, scale = 1, onCompose, submitting }: PaperDeskProps) {
  const emptyState = !exercise;

  return (
    <div className="flex-1 flex flex-col relative overflow-hidden">
      <div className="flex-1 overflow-y-auto scrollbar-hide p-6 flex flex-col items-center justify-center min-h-0">
        {emptyState ? (
          <motion.div 
            className="flex flex-col items-center gap-5"
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, ease: 'easeOut' }}
          >
            <Music size={160} className="text-[#E5E5EA]" strokeWidth={0.8} />
            <p className="text-base text-[#8E8E93] text-center max-w-sm" style={{ fontFamily: 'Inter, sans-serif' }}>
              Select parameters and press Compose
            </p>
          </motion.div>
        ) : (
          <div className="w-full max-w-[800px]">
            <div className="notation-paper max-w-[800px] min-h-[400px] mx-auto">
              <NotationPanel svg={exercise.svg} scale={scale} />
            </div>
          </div>
        )}
      </div>

      <div className="flex justify-center pb-6 relative z-10">
        <ComposePlate onClick={onCompose} disabled={submitting} label={submitting ? 'Composing...' : 'Compose'} />
      </div>
    </div>
  );
}
