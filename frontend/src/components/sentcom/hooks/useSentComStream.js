import { useCallback, useEffect, useRef, useState } from 'react';
import { safeGet } from '../../../utils/api';
import { safePolling } from '../../../utils/safePolling';
import { useDataCache } from '../../../contexts';
import { useWsData } from '../../../contexts/WebSocketDataContext';

export const useSentComStream = (pollInterval = 120000) => {  // HTTP backup only, WS is primary
  const { getCached, setCached } = useDataCache();
  const { sentcomData: wsSentcom } = useWsData();
  const isFirstMount = useRef(true);
  
  // Initialize from cache if available
  const cachedStream = getCached('sentcomStream');
  const [messages, setMessages] = useState(cachedStream?.data || []);
  const [loading, setLoading] = useState(!cachedStream?.data);
  const lastFetchRef = useRef({ ids: '', chatCount: 0 });

  const fetchStream = useCallback(async () => {
    try {
      const data = await safeGet('/api/sentcom/stream?limit=20');
      if (!data) return;
      
      if (data?.success && data.messages) {
        // Separate chat messages from status/system messages
        const chatMessages = data.messages.filter(m => 
          m.type === 'chat' || m.action_type === 'chat_response' || m.action_type === 'user_message'
        );
        const statusMessages = data.messages.filter(m => 
          m.type !== 'chat' && m.action_type !== 'chat_response' && m.action_type !== 'user_message'
        );
        
        // Only update if chat messages changed (ignore status message content changes)
        const chatIds = chatMessages.map(m => m.id || m.timestamp).join(',');
        const hasNewChat = chatIds !== lastFetchRef.current.ids || 
                          chatMessages.length !== lastFetchRef.current.chatCount;
        
        if (hasNewChat || messages.length === 0) {
          lastFetchRef.current = { ids: chatIds, chatCount: chatMessages.length };
          // Keep status messages stable - only take the 2 most recent
          const stableStatus = statusMessages.slice(0, 2);
          const newMessages = [...stableStatus, ...chatMessages];
          setMessages(newMessages);
          setCached('sentcomStream', newMessages, 30000); // 30 second TTL
        }
      }
    } catch (err) {
      console.error('Error fetching stream:', err);
    } finally {
      setLoading(false);
    }
  }, [messages.length, setCached]);

  useEffect(() => {
    // WS is primary source — delay initial HTTP fetch to reduce startup burst
    const cached = getCached('sentcomStream');
    if (cached?.data && isFirstMount.current) {
      setMessages(cached.data);
      setLoading(false);
    } else {
      const timer = setTimeout(() => fetchStream(), 7000);
      isFirstMount.current = false;
      return () => clearTimeout(timer);
    }
    isFirstMount.current = false;
    
    return safePolling(fetchStream, pollInterval, { immediate: false });
  }, [fetchStream, pollInterval, getCached]);

  // Subscribe to WS SentCom stream updates (supplements polling)
  useEffect(() => {
    if (!wsSentcom?.stream || !Array.isArray(wsSentcom.stream)) return;
    const streamMessages = wsSentcom.stream.map(m => ({ ...m, source: 'stream' }));
    if (streamMessages.length > 0) {
      setMessages(prev => {
        const chatMsgs = prev.filter(p => p.type === 'chat' || p.action_type === 'chat_response' || p.action_type === 'user_message');
        const merged = [...streamMessages.slice(0, 2), ...chatMsgs];
        return merged;
      });
      setLoading(false);
    }
  }, [wsSentcom?.stream]);

  return { messages, loading, refresh: fetchStream };
};
