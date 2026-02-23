import React, { useState, useEffect } from 'react';
import { Settings, Wifi, WifiOff, RefreshCw, Check, AlertCircle, ExternalLink, Terminal } from 'lucide-react';
import api from '../utils/api';

export default function SettingsPage() {
  const [config, setConfig] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [newOllamaUrl, setNewOllamaUrl] = useState('');
  const [message, setMessage] = useState(null);
  const [testing, setTesting] = useState(false);

  const fetchConfig = async () => {
    setLoading(true);
    try {
      const res = await api.get('/api/config');
      setConfig(res.data);
      setNewOllamaUrl(res.data.ollama_url || '');
    } catch (err) {
      console.error('Failed to fetch config:', err);
      setMessage({ type: 'error', text: 'Failed to load configuration' });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchConfig();
  }, []);

  const handleSaveOllamaUrl = async () => {
    if (!newOllamaUrl.trim()) {
      setMessage({ type: 'error', text: 'Please enter a valid URL' });
      return;
    }

    setSaving(true);
    setMessage(null);

    try {
      const res = await api.post('/api/config/ollama-url', { url: newOllamaUrl });
      setMessage({ type: 'success', text: res.data.message });
      await fetchConfig(); // Refresh config
    } catch (err) {
      const detail = err.response?.data?.detail || 'Failed to update URL';
      setMessage({ type: 'error', text: detail });
    } finally {
      setSaving(false);
    }
  };

  const handleTestConnection = async () => {
    setTesting(true);
    setMessage(null);
    try {
      await fetchConfig();
      if (config?.ollama_connected) {
        setMessage({ type: 'success', text: 'Connection successful!' });
      } else {
        setMessage({ type: 'error', text: 'Connection failed. Check if Ollama is running and tunnel is active.' });
      }
    } catch (err) {
      setMessage({ type: 'error', text: 'Connection test failed' });
    } finally {
      setTesting(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <RefreshCw className="w-6 h-6 animate-spin text-cyan-400" />
      </div>
    );
  }

  return (
    <div className="max-w-3xl mx-auto space-y-6" data-testid="settings-page">
      {/* Header */}
      <div className="flex items-center gap-3">
        <div className="p-2 rounded-lg bg-cyan-500/10 border border-cyan-500/20">
          <Settings className="w-6 h-6 text-cyan-400" />
        </div>
        <div>
          <h1 className="text-2xl font-bold text-white">Settings</h1>
          <p className="text-sm text-zinc-500">Configure your local AI assistant connection</p>
        </div>
      </div>

      {/* Message */}
      {message && (
        <div className={`p-4 rounded-lg flex items-center gap-3 ${
          message.type === 'success' 
            ? 'bg-green-500/10 border border-green-500/30 text-green-400'
            : 'bg-red-500/10 border border-red-500/30 text-red-400'
        }`}>
          {message.type === 'success' ? <Check className="w-5 h-5" /> : <AlertCircle className="w-5 h-5" />}
          <span>{message.text}</span>
        </div>
      )}

      {/* Ollama Configuration */}
      <div className="glass-panel p-6 space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <h2 className="text-lg font-semibold text-white">Local AI (Ollama)</h2>
            <div className={`flex items-center gap-1.5 px-2 py-1 rounded-full text-xs font-medium ${
              config?.ollama_connected
                ? 'bg-green-500/10 text-green-400 border border-green-500/30'
                : 'bg-red-500/10 text-red-400 border border-red-500/30'
            }`}>
              {config?.ollama_connected ? <Wifi className="w-3 h-3" /> : <WifiOff className="w-3 h-3" />}
              {config?.ollama_connected ? 'Connected' : 'Disconnected'}
            </div>
          </div>
          <button
            onClick={handleTestConnection}
            disabled={testing}
            className="px-3 py-1.5 text-sm rounded-lg bg-zinc-800 hover:bg-zinc-700 text-zinc-300 border border-zinc-700 flex items-center gap-2 transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`w-4 h-4 ${testing ? 'animate-spin' : ''}`} />
            Test
          </button>
        </div>

        <div className="space-y-2">
          <label className="text-sm text-zinc-400">Tunnel URL</label>
          <div className="flex gap-2">
            <input
              type="text"
              value={newOllamaUrl}
              onChange={(e) => setNewOllamaUrl(e.target.value)}
              placeholder="https://your-tunnel.trycloudflare.com"
              className="flex-1 bg-zinc-900 border border-zinc-700 rounded-lg px-4 py-2.5 text-white placeholder-zinc-600 focus:outline-none focus:border-cyan-500/50 focus:ring-1 focus:ring-cyan-500/30"
              data-testid="ollama-url-input"
            />
            <button
              onClick={handleSaveOllamaUrl}
              disabled={saving || newOllamaUrl === config?.ollama_url}
              className="px-4 py-2 rounded-lg bg-cyan-500 hover:bg-cyan-600 text-black font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
              data-testid="save-ollama-url-btn"
            >
              {saving ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />}
              Save
            </button>
          </div>
          <p className="text-xs text-zinc-500">
            Current model: <span className="text-cyan-400 font-mono">{config?.ollama_model || 'Not set'}</span>
          </p>
        </div>
      </div>

      {/* Daily Startup Guide */}
      <div className="glass-panel p-6 space-y-4">
        <div className="flex items-center gap-3">
          <Terminal className="w-5 h-5 text-purple-400" />
          <h2 className="text-lg font-semibold text-white">Daily Startup Guide</h2>
        </div>

        <div className="space-y-4 text-sm">
          <div className="flex gap-4">
            <div className="flex-shrink-0 w-8 h-8 rounded-full bg-cyan-500/20 border border-cyan-500/30 flex items-center justify-center text-cyan-400 font-bold">1</div>
            <div>
              <p className="text-white font-medium">Start Ollama</p>
              <p className="text-zinc-500">Make sure Ollama is running on your local machine (usually starts automatically)</p>
            </div>
          </div>

          <div className="flex gap-4">
            <div className="flex-shrink-0 w-8 h-8 rounded-full bg-cyan-500/20 border border-cyan-500/30 flex items-center justify-center text-cyan-400 font-bold">2</div>
            <div>
              <p className="text-white font-medium">Start Cloudflare Tunnel</p>
              <p className="text-zinc-500 mb-2">Open PowerShell and run:</p>
              <code className="block bg-zinc-900 border border-zinc-700 rounded-lg px-3 py-2 text-cyan-400 font-mono text-xs">
                cloudflared tunnel --url http://localhost:11434
              </code>
            </div>
          </div>

          <div className="flex gap-4">
            <div className="flex-shrink-0 w-8 h-8 rounded-full bg-cyan-500/20 border border-cyan-500/30 flex items-center justify-center text-cyan-400 font-bold">3</div>
            <div>
              <p className="text-white font-medium">Copy the Tunnel URL</p>
              <p className="text-zinc-500">Look for a URL like <code className="text-purple-400">https://something-random.trycloudflare.com</code> in the terminal output</p>
            </div>
          </div>

          <div className="flex gap-4">
            <div className="flex-shrink-0 w-8 h-8 rounded-full bg-cyan-500/20 border border-cyan-500/30 flex items-center justify-center text-cyan-400 font-bold">4</div>
            <div>
              <p className="text-white font-medium">Update the URL Above</p>
              <p className="text-zinc-500">Paste the new tunnel URL in the input field above and click Save</p>
            </div>
          </div>
        </div>

        <div className="mt-4 p-3 rounded-lg bg-purple-500/10 border border-purple-500/20">
          <p className="text-xs text-purple-300">
            <strong>Tip:</strong> Keep the PowerShell window open while using the app. The tunnel will close when you close the terminal.
          </p>
        </div>
      </div>

      {/* External Links */}
      <div className="glass-panel p-6">
        <h2 className="text-lg font-semibold text-white mb-4">Resources</h2>
        <div className="flex flex-wrap gap-3">
          <a
            href="https://ollama.ai"
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-zinc-300 border border-zinc-700 transition-colors"
          >
            <ExternalLink className="w-4 h-4" />
            Ollama Website
          </a>
          <a
            href="https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/"
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-zinc-300 border border-zinc-700 transition-colors"
          >
            <ExternalLink className="w-4 h-4" />
            Cloudflare Tunnel Docs
          </a>
        </div>
      </div>
    </div>
  );
}
