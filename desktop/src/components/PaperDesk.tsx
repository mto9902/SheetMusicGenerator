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
    <div className="h-full min-h-0 flex flex-col relative overflow-hidden">
      <div
        className={`panel-card flex-1 min-h-0 overflow-hidden p-6 flex flex-col items-center ${
          emptyState ? 'justify-center' : 'justify-start'
        }`}
      >
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
          <div className="score-viewport w-full h-full min-h-0 mx-auto">
            <div className="score-paper-fixed h-full min-h-0 mx-auto">
              <NotationPanel svg={exercise.svg} scale={scale} />
            </div>
          </div>
        )}
      </div>

      <div className="flex justify-center py-4 shrink-0 relative z-10">
        <ComposePlate onClick={onCompose} disabled={submitting} label={submitting ? 'Composing...' : 'Compose'} />
      </div>
    </div>
  );
}
