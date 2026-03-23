export { default as useWebSocket } from './useWebSocket';
export { default as usePriceAlerts } from './usePriceAlerts';
export { useSmartPolling, useFetchOnce } from './useSmartPolling';

// Re-export focus-aware polling from context for convenience
export { useFocusAwarePolling } from '../contexts/FocusModeContext';

// SentCom hooks
export {
  useAIInsights,
  useMarketSession,
  useSentComStatus,
  useSentComStream,
  useSentComPositions,
  useSentComSetups,
  useSentComContext,
  useSentComAlerts,
  useChatHistory,
  useTradingBotControl,
  useIBConnectionStatus,
  useAIModules,
} from './useSentCom';
