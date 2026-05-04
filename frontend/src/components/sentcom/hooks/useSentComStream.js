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
      // 2026-05-04 — bumped from limit=20 → 200 so operator can scroll
      // back through scanner events / EVAL gates / fills during RTH.
      // The 20-cap was a relic of the early build when the stream was
      // chat-only; now it's the operator's primary forensics surface.
      const data = await safeGet('/api/sentcom/stream?limit=200');
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
        
        // 2026-05-04 — also re-render when status volume changes so new
        // scanner / eval / fill events flow in without waiting for a
        // chat message to refresh.
        const statusCountChanged = statusMessages.length !== (lastFetchRef.current.statusCount ?? 0);
        if (hasNewChat || statusCountChanged || messages.length === 0) {
          lastFetchRef.current = {
            ids: chatIds,
            chatCount: chatMessages.length,
            statusCount: statusMessages.length,
          };
          // 2026-05-04 — was `.slice(0, 2)` which artificially capped the
          // Unified Stream to 2 status events even when the backend
          // returned hundreds. Remove the cap so the operator can scroll
          // back through the full RTH event log.
          const newMessages = [...statusMessages, ...chatMessages];
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
        // 2026-05-04 — was `.slice(0, 2)` which clipped every WS update
        // to 2 most-recent stream events, masking the live SCAN/EVAL/
        // FILL flow during RTH. Use the full WS payload (already capped
        // by backend broadcaster).
        const merged = [...streamMessages, ...chatMsgs];
        return merged;
      });
      setLoading(false);
    }
  }, [wsSentcom?.stream]);

  return { messages, loading, refresh: fetchStream };
};
