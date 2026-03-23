/**
 * TrainingModeIndicator - Shows when AI training is active
 * 
 * Displays a subtle indicator that training is happening and polling is reduced.
 * This helps users understand why data might be refreshing slower.
 */

import React from 'react';
import { Brain, Loader2 } from 'lucide-react';
import { useTrainingMode } from '../contexts';

const TrainingModeIndicator = () => {
  const { isTrainingActive, trainingType, getTrainingStats } = useTrainingMode();
  
  if (!isTrainingActive) return null;
  
  const stats = getTrainingStats();
  const elapsedMinutes = Math.floor(stats.elapsedMs / 60000);
  
  return (
    <div 
      className="fixed bottom-20 right-4 z-40 flex items-center gap-2 px-3 py-2 rounded-lg 
                 bg-purple-500/20 border border-purple-500/40 text-purple-300 text-xs
                 animate-pulse"
      title="AI training in progress - polling reduced to prevent resource exhaustion"
      data-testid="training-mode-indicator"
    >
      <Brain className="w-4 h-4" />
      <Loader2 className="w-3 h-3 animate-spin" />
      <span>
        Training {trainingType || 'AI'}
        {elapsedMinutes > 0 && ` (${elapsedMinutes}m)`}
      </span>
    </div>
  );
};

export default TrainingModeIndicator;
