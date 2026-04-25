import { motion, AnimatePresence } from 'framer-motion';
import { ChevronUp, Clock } from 'lucide-react';
import type { ExerciseListItem } from '@shared/types';

interface HistoryDrawerProps {
  exercises: ExerciseListItem[];
  activeId?: string | null;
  open: boolean;
  onToggle: () => void;
  onSelect: (exerciseId: string) => void;
}

export function HistoryDrawer({ exercises, activeId, open, onToggle, onSelect }: HistoryDrawerProps) {
  return (
    <div className="absolute bottom-0 left-0 right-0 z-40">
      {/* Tab */}
      <div className="flex justify-center">
        <button
          type="button"
          className="flex items-center gap-2 px-6 py-2.5 bg-white border border-[#E5E5EA] border-b-0 rounded-t-lg text-sm font-medium text-[#1C1C1E] cursor-pointer hover:bg-[#F5F5F7] transition-colors"
          onClick={onToggle}
        >
          <span>History</span>
          <motion.div animate={{ rotate: open ? 180 : 0 }} transition={{ duration: 0.2 }}>
            <ChevronUp size={16} className="text-[#8E8E93]" />
          </motion.div>
          {exercises.length > 0 && (
            <span className="text-xs text-[#8E8E93] bg-[#F5F5F7] px-1.5 py-0.5 rounded">
              {exercises.length}
            </span>
          )}
        </button>
      </div>

      {/* Drawer Panel */}
      <AnimatePresence>
        {open && (
          <motion.div
            className="bottom-bar overflow-hidden"
            initial={{ height: 0 }}
            animate={{ height: 280 }}
            exit={{ height: 0 }}
            transition={{ duration: 0.25, ease: 'easeOut' }}
          >
            <div className="h-full overflow-y-auto scrollbar-hide">
              {exercises.length === 0 ? (
                <div className="h-full flex items-center justify-center">
                  <p className="text-sm text-[#C7C7CC]">
                    No compositions yet. Press Compose to begin.
                  </p>
                </div>
              ) : (
                <div>
                  {exercises.map((exercise) => (
                    <div
                      key={exercise.exerciseId}
                      className={`history-row ${activeId === exercise.exerciseId ? 'active' : ''}`}
                      onClick={() => onSelect(exercise.exerciseId)}
                    >
                      <Clock size={14} className="text-[#C7C7CC] mr-2 shrink-0" />
                      <span className="text-sm text-[#1C1C1E] flex-1 truncate">
                        {exercise.title}
                      </span>
                      <span className="text-xs text-[#8E8E93] shrink-0">
                        Grade {exercise.grade} | {exercise.config.timeSignature}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
