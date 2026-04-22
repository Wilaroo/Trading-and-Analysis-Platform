import React, { useState } from 'react';
import { Loader, Send } from 'lucide-react';

export const ChatInput = ({ onSend, disabled }) => {
  const [message, setMessage] = useState('');
  const [sending, setSending] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!message.trim() || sending) return;
    
    setSending(true);
    await onSend?.(message);
    setMessage('');
    setSending(false);
  };

  return (
    <form onSubmit={handleSubmit} className="p-4 border-t border-white/5">
      <div className="flex gap-2">
        <input
          type="text"
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          placeholder="Ask SentCom anything..."
          disabled={disabled || sending}
          className="flex-1 bg-black/40 border border-white/10 rounded-xl px-4 py-3 text-sm text-white placeholder-zinc-500 focus:outline-none focus:border-cyan-500/50"
        />
        <button
          type="submit"
          disabled={!message.trim() || sending || disabled}
          className="px-4 py-3 rounded-xl bg-gradient-to-r from-cyan-500 to-violet-500 text-white font-medium disabled:opacity-50 disabled:cursor-not-allowed hover:opacity-90 transition-opacity"
        >
          {sending ? <Loader className="w-5 h-5 animate-spin" /> : <Send className="w-5 h-5" />}
        </button>
      </div>
    </form>
  );
};
