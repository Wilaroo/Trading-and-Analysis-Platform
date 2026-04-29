import React, { useState, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Upload, Download, FileText, RefreshCw, Check, X, Trash2,
  Zap, BookOpen, AlertCircle, ChevronDown, ChevronRight, Sparkles
} from 'lucide-react';
import api from '../../utils/api';

// TraderSync Import Component
const TraderSyncImport = ({ onImportComplete }) => {
  const [batches, setBatches] = useState([]);
  const [loading, setLoading] = useState(false);
  const [importing, setImporting] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [candidates, setCandidates] = useState(null);
  const [generationResults, setGenerationResults] = useState(null);
  const [expandedBatch, setExpandedBatch] = useState(null);
  const [dragActive, setDragActive] = useState(false);
  const [importResult, setImportResult] = useState(null);

  const loadBatches = useCallback(async () => {
    try {
      setLoading(true);
      const res = await api.get('/api/journal/tradersync/batches');
      setBatches(res.data.batches || []);
    } catch (err) {
      console.error('Failed to load batches:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadBatches();
  }, [loadBatches]);

  const handleFileUpload = async (file) => {
    if (!file || !file.name.endsWith('.csv')) {
      alert('Please upload a CSV file');
      return;
    }

    setImporting(true);
    setImportResult(null);

    try {
      const content = await file.text();
      const res = await api.post('/api/journal/tradersync/import', {
        csv_content: content,
        batch_name: file.name
      });

      if (res.data.success) {
        setImportResult(res.data);
        await loadBatches();
        onImportComplete?.();
      }
    } catch (err) {
      console.error('Import failed:', err);
      setImportResult({ error: err.message || 'Import failed' });
    } finally {
      setImporting(false);
    }
  };

  const handleDrop = (e) => {
    e.preventDefault();
    setDragActive(false);
    const file = e.dataTransfer.files[0];
    if (file) handleFileUpload(file);
  };

  const handleDragOver = (e) => {
    e.preventDefault();
    setDragActive(true);
  };

  const handleDragLeave = () => {
    setDragActive(false);
  };

  const loadPlaybookCandidates = async () => {
    try {
      setLoading(true);
      const res = await api.get('/api/journal/tradersync/playbook-candidates?min_trades_per_setup=2');
      setCandidates(res.data);
    } catch (err) {
      console.error('Failed to load candidates:', err);
    } finally {
      setLoading(false);
    }
  };

  const generateAllPlaybooks = async () => {
    setGenerating(true);
    setGenerationResults(null);

    try {
      const res = await api.post('/api/journal/ai/generate-playbooks-from-tradersync?min_trades=2');
      setGenerationResults(res.data);
      onImportComplete?.();
    } catch (err) {
      console.error('Generation failed:', err);
      setGenerationResults({ error: err.message || 'Generation failed' });
    } finally {
      setGenerating(false);
    }
  };

  const savePlaybook = async (playbook) => {
    try {
      const res = await api.post('/api/journal/playbooks/save-generated', playbook);
      if (res.data.success) {
        // Update results to show saved
        setGenerationResults(prev => ({
          ...prev,
          results: prev.results.map(r => 
            r.playbook?.name === playbook.name 
              ? { ...r, status: 'saved' }
              : r
          )
        }));
      }
    } catch (err) {
      console.error('Failed to save playbook:', err);
    }
  };

  const deleteBatch = async (batchId) => {
    if (!window.confirm('Delete this import batch?')) return;
    
    try {
      await api.delete(`/api/journal/tradersync/batch/${batchId}`);
      await loadBatches();
    } catch (err) {
      console.error('Failed to delete batch:', err);
    }
  };

  return (
    <div className="space-y-4" data-testid="tradersync-import">
      {/* Import Section */}
      <div className="p-4 rounded-lg bg-gradient-to-br from-cyan-500/10 to-purple-500/10 border border-cyan-500/20">
        <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
          <Upload className="w-4 h-4 text-cyan-400" />
          Import from TraderSync
        </h3>
        
        {/* Drag & Drop Zone */}
        <div
          onDrop={handleDrop}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          className={`border-2 border-dashed rounded-lg p-6 text-center transition-colors ${
            dragActive ? 'border-cyan-500 bg-cyan-500/10' : 'border-white/20 hover:border-white/40'
          }`}
        >
          {importing ? (
            <div className="flex items-center justify-center gap-2">
              <RefreshCw className="w-5 h-5 animate-spin text-cyan-400" />
              <span className="text-zinc-400">Importing trades...</span>
            </div>
          ) : (
            <>
              <FileText className="w-8 h-8 mx-auto mb-2 text-zinc-500" />
              <p className="text-sm text-zinc-400 mb-2">
                Drag & drop TraderSync CSV here, or
              </p>
              <label className="cursor-pointer">
                <input
                  type="file"
                  accept=".csv"
                  className="hidden"
                  onChange={(e) => e.target.files?.[0] && handleFileUpload(e.target.files[0])}
                />
                <span className="text-cyan-400 hover:text-cyan-300 underline">browse files</span>
              </label>
            </>
          )}
        </div>

        {/* Import Result */}
        {importResult && (
          <div className={`mt-3 p-3 rounded-lg ${
            importResult.error ? 'bg-red-500/10 border border-red-500/30' : 'bg-emerald-500/10 border border-emerald-500/30'
          }`}>
            {importResult.error ? (
              <p className="text-sm text-red-400">{importResult.error}</p>
            ) : (
              <div className="text-sm">
                <p className="text-emerald-400 font-medium">
                  <Check className="w-4 h-4 inline mr-1" />
                  Imported {importResult.total_trades} trades
                </p>
                <p className="text-zinc-400 mt-1">
                  Symbols: {importResult.symbols?.slice(0, 10).join(', ')}
                  {importResult.symbols?.length > 10 && `... +${importResult.symbols.length - 10} more`}
                </p>
                {importResult.setup_types?.length > 0 && (
                  <p className="text-zinc-400">
                    Setup types: {importResult.setup_types.slice(0, 5).join(', ')}
                  </p>
                )}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Import Batches */}
      {batches.length > 0 && (
        <div className="p-3 rounded-lg bg-white/5 border border-white/10">
          <h4 className="text-xs text-zinc-500 uppercase mb-2">Previous Imports</h4>
          <div className="space-y-2 max-h-48 overflow-y-auto">
            {batches.map((batch) => (
              <div
                key={batch.batch_id}
                className="flex items-center justify-between p-2 rounded bg-black/30 hover:bg-black/40"
              >
                <div>
                  <p className="text-xs text-white">{batch.trade_count} trades</p>
                  <p className="text-[12px] text-zinc-500">
                    {new Date(batch.imported_at).toLocaleDateString()} • 
                    ${batch.total_pnl?.toFixed(0)} P&L • 
                    {batch.symbol_count} symbols
                  </p>
                </div>
                <button
                  onClick={() => deleteBatch(batch.batch_id)}
                  className="text-zinc-500 hover:text-red-400 p-1"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* AI Playbook Generation Section */}
      <div className="p-4 rounded-lg bg-gradient-to-br from-purple-500/10 to-amber-500/10 border border-purple-500/20">
        <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
          <Sparkles className="w-4 h-4 text-purple-400" />
          AI Playbook Generation
        </h3>
        
        <p className="text-xs text-zinc-400 mb-3">
          Analyze your TraderSync trades and auto-generate playbooks for winning setups.
        </p>

        <div className="flex gap-2">
          <button
            onClick={loadPlaybookCandidates}
            disabled={loading}
            className="px-3 py-1.5 rounded bg-white/10 text-white text-xs hover:bg-white/20 flex items-center gap-1 disabled:opacity-50"
          >
            {loading ? <RefreshCw className="w-3 h-3 animate-spin" /> : <BookOpen className="w-3 h-3" />}
            Find Candidates
          </button>
          <button
            onClick={generateAllPlaybooks}
            disabled={generating || batches.length === 0}
            className="px-3 py-1.5 rounded bg-purple-500 text-white text-xs font-medium hover:bg-purple-400 flex items-center gap-1 disabled:opacity-50"
          >
            {generating ? <RefreshCw className="w-3 h-3 animate-spin" /> : <Zap className="w-3 h-3" />}
            Generate All Playbooks
          </button>
        </div>

        {/* Candidates */}
        {candidates && (
          <div className="mt-3 p-3 rounded bg-black/30 border border-white/10">
            <p className="text-xs text-zinc-400 mb-2">
              Found {candidates.total_setups} setup types with multiple winning trades:
            </p>
            <div className="space-y-1 max-h-32 overflow-y-auto">
              {candidates.setup_types?.map((setup) => (
                <div key={setup._id} className="flex justify-between text-xs">
                  <span className="text-white">{setup._id}</span>
                  <span className="text-zinc-500">
                    {setup.count} trades • ${setup.total_pnl?.toFixed(0)}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Generation Results */}
        {generationResults && (
          <div className="mt-3 space-y-2">
            {generationResults.error ? (
              <div className="p-2 rounded bg-red-500/10 border border-red-500/30">
                <p className="text-sm text-red-400">{generationResults.error}</p>
              </div>
            ) : (
              <>
                <div className="p-2 rounded bg-emerald-500/10 border border-emerald-500/30">
                  <p className="text-sm text-emerald-400">
                    Generated {generationResults.playbooks_generated} playbooks
                    {generationResults.playbooks_skipped > 0 && ` (${generationResults.playbooks_skipped} skipped)`}
                  </p>
                </div>
                
                {/* Generated Playbooks */}
                <div className="space-y-2 max-h-64 overflow-y-auto">
                  {generationResults.results?.filter(r => r.status === 'generated').map((result, idx) => (
                    <div key={idx} className="p-2 rounded bg-black/30 border border-white/10">
                      <div className="flex items-center justify-between">
                        <div>
                          <p className="text-xs font-medium text-white">{result.playbook?.name}</p>
                          <p className="text-[12px] text-zinc-500">{result.setup_type}</p>
                        </div>
                        <button
                          onClick={() => savePlaybook(result.playbook)}
                          disabled={result.status === 'saved'}
                          className={`px-2 py-1 rounded text-[12px] font-medium ${
                            result.status === 'saved'
                              ? 'bg-emerald-500/20 text-emerald-400'
                              : 'bg-cyan-500 text-black hover:bg-cyan-400'
                          }`}
                        >
                          {result.status === 'saved' ? 'Saved' : 'Save'}
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

export default TraderSyncImport;
