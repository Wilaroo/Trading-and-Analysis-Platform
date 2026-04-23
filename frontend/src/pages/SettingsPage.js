import React, { useState, useEffect } from 'react';
import { Settings, Wifi, WifiOff, RefreshCw, Check, AlertCircle, ExternalLink, Terminal, Cpu, Volume2, VolumeX, Bell } from 'lucide-react';
import api from '../utils/api';

export default function SettingsPage({ audioEnabled, setAudioEnabled, alertThreshold, setAlertThreshold }) {
  const [config, setConfig] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [newOllamaUrl, setNewOllamaUrl] = useState('');
  const [selectedModel, setSelectedModel] = useState('qwen2.5:3b');
  const [modelSaving, setModelSaving] = useState(false);
  const [message, setMessage] = useState(null);
  const [testing, setTesting] = useState(false);

  const OLLAMA_MODELS = [
    { id: 'qwen2.5:3b', name: 'Qwen 2.5 3B', description: 'Faster responses, lower memory', speed: 'Fast' },
    { id: 'qwen2.5:7b', name: 'Qwen 2.5 7B', description: 'Smarter responses, more detailed', speed: 'Balanced' },
    { id: 'llama3:8b', name: 'Llama 3 8B', description: 'General purpose, good quality', speed: 'Balanced' },
  ];

  const fetchConfig = async () => {
    setLoading(true);
    try {
      const res = await api.get('/api/config');
      setConfig(res.data);
      setNewOllamaUrl(res.data.ollama_url || '');
      setSelectedModel(res.data.ollama_model || 'qwen2.5:3b');
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
      const res = await api.get('/api/config/test-connection');
      if (res.data?.connected) {
        setConfig(prev => ({ ...prev, ollama_connected: true }));
        const models = res.data.models?.join(', ') || 'unknown';
        setMessage({ type: 'success', text: `Connected! Available models: ${models}` });
      } else {
        setConfig(prev => ({ ...prev, ollama_connected: false }));
        setMessage({ type: 'error', text: res.data?.error || 'Connection failed' });
      }
    } catch (err) {
      setMessage({ type: 'error', text: 'Connection test failed - check if tunnel is running' });
    } finally {
      setTesting(false);
    }
  };

  const handleModelChange = async (modelId) => {
    setModelSaving(true);
    try {
      await api.post('/api/config/ollama-model', { model: modelId });
      setSelectedModel(modelId);
      setConfig(prev => ({ ...prev, ollama_model: modelId }));
      setMessage({ type: 'success', text: `Switched to ${modelId}` });
    } catch (err) {
      setMessage({ type: 'error', text: 'Failed to change model' });
    } finally {
      setModelSaving(false);
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

      {/* Price Alerts — audio toggle + threshold. Moved here from the floating
          bottom-right cluster so it no longer overlaps the SentCom V5 chat bubble.
          State lives in App.js and is passed down as props. */}
      {typeof setAudioEnabled === 'function' && (
        <div className="glass-panel p-6 space-y-4" data-testid="alerts-settings-card">
          <div className="flex items-center gap-3">
            <div className="p-1.5 rounded-lg bg-amber-500/10 border border-amber-500/20">
              <Bell className="w-5 h-5 text-amber-400" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-white">Price Alerts</h2>
              <p className="text-xs text-zinc-500">Audio chime when a ticker moves past your threshold vs. today's open.</p>
            </div>
          </div>

          <div className="flex items-center justify-between p-4 rounded-lg bg-zinc-900/60 border border-zinc-800">
            <div>
              <div className="text-sm text-white font-medium">Audio alerts</div>
              <div className="text-xs text-zinc-500">
                {audioEnabled ? 'On — you\'ll hear a sound on every alert' : 'Off — alerts still appear as toasts'}
              </div>
            </div>
            <button
              onClick={() => setAudioEnabled(!audioEnabled)}
              data-testid="toggle-audio-alerts"
              className={`p-3 rounded-lg transition-all border ${
                audioEnabled
                  ? 'bg-cyan-500/15 text-cyan-300 border-cyan-500/40 hover:bg-cyan-500/25'
                  : 'bg-zinc-800 text-zinc-500 border-zinc-700 hover:text-zinc-300'
              }`}
              title={audioEnabled ? 'Disable audio alerts' : 'Enable audio alerts'}
            >
              {audioEnabled ? <Volume2 className="w-5 h-5" /> : <VolumeX className="w-5 h-5" />}
            </button>
          </div>

          <div className="p-4 rounded-lg bg-zinc-900/60 border border-zinc-800 space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-sm text-white font-medium">Alert threshold</span>
              <span className="text-sm font-mono text-cyan-300">±{alertThreshold}%</span>
            </div>
            <input
              type="range"
              min="0.5"
              max="10"
              step="0.5"
              value={alertThreshold}
              onChange={(e) => setAlertThreshold(parseFloat(e.target.value))}
              className="w-full accent-cyan-500"
              data-testid="alert-threshold-slider"
            />
            <div className="flex justify-between text-xs text-zinc-500">
              <span>0.5%</span>
              <span>5%</span>
              <span>10%</span>
            </div>
            <p className="text-xs text-zinc-500">
              Alerts fire when a watchlist ticker moves ≥ {alertThreshold}% from today's open.
            </p>
          </div>
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

      {/* Ollama Model Selection */}
      <div className="glass-panel p-6 space-y-4">
        <div className="flex items-center gap-3">
          <Cpu className="w-5 h-5 text-purple-400" />
          <h2 className="text-lg font-semibold text-white">AI Model Selection</h2>
        </div>
        <p className="text-sm text-zinc-400">Choose the Ollama model for AI responses. Faster models use less memory but may be less detailed.</p>
        
        <div className="grid gap-3">
          {OLLAMA_MODELS.map((model) => (
            <button
              key={model.id}
              onClick={() => handleModelChange(model.id)}
              disabled={modelSaving}
              className={`p-4 rounded-lg border text-left transition-all ${
                selectedModel === model.id
                  ? 'bg-cyan-500/10 border-cyan-500/50 ring-1 ring-cyan-500/30'
                  : 'bg-zinc-800/50 border-zinc-700 hover:border-zinc-600'
              }`}
              data-testid={`model-option-${model.id}`}
            >
              <div className="flex items-center justify-between">
                <div>
                  <div className="flex items-center gap-2">
                    <span className={`text-sm font-semibold ${selectedModel === model.id ? 'text-cyan-400' : 'text-white'}`}>
                      {model.name}
                    </span>
                    <span className={`text-[10px] px-1.5 py-0.5 rounded ${
                      model.speed === 'Fast' ? 'bg-green-500/20 text-green-400' :
                      'bg-yellow-500/20 text-yellow-400'
                    }`}>
                      {model.speed}
                    </span>
                  </div>
                  <p className="text-xs text-zinc-500 mt-1">{model.description}</p>
                </div>
                {selectedModel === model.id && (
                  <Check className="w-5 h-5 text-cyan-400" />
                )}
                {modelSaving && selectedModel !== model.id && (
                  <RefreshCw className="w-4 h-4 text-zinc-500 animate-spin" />
                )}
              </div>
            </button>
          ))}
        </div>
      </div>

      {/* Daily Startup Guide */}
      <div className="glass-panel p-6 space-y-4">
        <div className="flex items-center gap-3">
          <Terminal className="w-5 h-5 text-purple-400" />
          <h2 className="text-lg font-semibold text-white">Daily Startup Guide (ngrok)</h2>
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
              <p className="text-white font-medium">Start ngrok Tunnel</p>
              <p className="text-zinc-500 mb-2">Open PowerShell and run:</p>
              <code className="block bg-zinc-900 border border-zinc-700 rounded-lg px-3 py-2 text-cyan-400 font-mono text-xs">
                ngrok http 11434
              </code>
            </div>
          </div>

          <div className="flex gap-4">
            <div className="flex-shrink-0 w-8 h-8 rounded-full bg-cyan-500/20 border border-cyan-500/30 flex items-center justify-center text-cyan-400 font-bold">3</div>
            <div>
              <p className="text-white font-medium">Your URL is Static (Paid Plan)</p>
              <p className="text-zinc-500">With ngrok Hobby plan, your URL stays the same! No need to update it daily.</p>
              <p className="text-zinc-500 mt-1">Current URL: <code className="text-green-400">pseudoaccidentally-linty-addie.ngrok-free.dev</code></p>
            </div>
          </div>

          <div className="flex gap-4">
            <div className="flex-shrink-0 w-8 h-8 rounded-full bg-cyan-500/20 border border-cyan-500/30 flex items-center justify-center text-cyan-400 font-bold">4</div>
            <div>
              <p className="text-white font-medium">Click Test to Verify</p>
              <p className="text-zinc-500">Click the Test button above to confirm the connection is working</p>
            </div>
          </div>
        </div>

        <div className="mt-4 p-3 rounded-lg bg-green-500/10 border border-green-500/20">
          <p className="text-xs text-green-300">
            <strong>Pro Tip:</strong> With ngrok paid plan, your tunnel URL is permanent! Just start ngrok each session and you're good to go.
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
            href="https://ngrok.com/docs"
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-zinc-300 border border-zinc-700 transition-colors"
          >
            <ExternalLink className="w-4 h-4" />
            ngrok Docs
          </a>
        </div>
      </div>
    </div>
  );
}
