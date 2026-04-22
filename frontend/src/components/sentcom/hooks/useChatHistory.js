import { useCallback, useEffect, useState } from 'react';
import { safeGet } from '../../../utils/api';

// Hook for persisted chat history
export const useChatHistory = () => {
  const [chatHistory, setChatHistory] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(false);

  const fetchChatHistory = useCallback(async () => {
    if (loaded) return; // Only load once
    
    try {
      const data = await safeGet('/api/sentcom/chat/history?limit=50');
      if (data?.success && data.messages) {
        // Convert to local message format and reverse for newest-first display
        const formattedMessages = data.messages.map((msg, idx) => ({
          id: `history_${idx}_${Date.now()}`,
          type: 'chat',
          content: msg.content,
          timestamp: msg.timestamp,
          action_type: msg.role === 'user' ? 'user_message' : 'chat_response',
          metadata: { role: msg.role }
        })).reverse();
        
        setChatHistory(formattedMessages);
        setLoaded(true);
      }
    } catch (err) {
      console.error('Error fetching chat history:', err);
    } finally {
      setLoading(false);
    }
  }, [loaded]);

  useEffect(() => {
    fetchChatHistory();
  }, [fetchChatHistory]);

  return { chatHistory, loading, refresh: fetchChatHistory };
};
