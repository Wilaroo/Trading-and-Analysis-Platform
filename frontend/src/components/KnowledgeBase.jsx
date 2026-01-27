import React, { useState, useEffect, useCallback } from 'react';
import { 
  BookOpen, Plus, Search, X, Tag, Brain, Target, 
  Lightbulb, FileText, CheckSquare, TrendingUp, 
  ChevronDown, Edit2, Trash2, Save, Loader2
} from 'lucide-react';
import api from '../utils/api';
import { toast } from 'sonner';

const TYPES = [
  { value: 'strategy', label: 'Strategy', icon: Target, color: 'text-purple-400' },
  { value: 'pattern', label: 'Pattern', icon: TrendingUp, color: 'text-blue-400' },
  { value: 'insight', label: 'Insight', icon: Lightbulb, color: 'text-yellow-400' },
  { value: 'rule', label: 'Rule', icon: CheckSquare, color: 'text-green-400' },
  { value: 'note', label: 'Note', icon: FileText, color: 'text-zinc-400' },
  { value: 'indicator', label: 'Indicator', icon: TrendingUp, color: 'text-cyan-400' },
  { value: 'checklist', label: 'Checklist', icon: CheckSquare, color: 'text-orange-400' },
];

const CATEGORIES = [
  'entry', 'exit', 'risk_management', 'position_sizing',
  'market_condition', 'technical', 'fundamental', 'sentiment',
  'premarket', 'intraday', 'swing', 'general'
];

const KnowledgeBase = ({ isOpen, onClose }) => {
  const [entries, setEntries] = useState([]);
  const [loading, setLoading] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [filterType, setFilterType] = useState('');
  const [filterCategory, setFilterCategory] = useState('');
  const [showAddForm, setShowAddForm] = useState(false);
  const [editingEntry, setEditingEntry] = useState(null);
  const [stats, setStats] = useState(null);
  
  // Form state
  const [formData, setFormData] = useState({
    title: '',
    content: '',
    type: 'note',
    category: 'general',
    tags: '',
    confidence: 80,
    source: 'user'
  });

  const fetchEntries = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (searchQuery) params.append('q', searchQuery);
      if (filterType) params.append('type', filterType);
      if (filterCategory) params.append('category', filterCategory);
      
      const res = await api.get(`/api/knowledge?${params.toString()}`);
      setEntries(res.data.results || []);
    } catch (err) {
      console.error('Error fetching knowledge:', err);
      toast.error('Failed to load knowledge base');
    } finally {
      setLoading(false);
    }
  }, [searchQuery, filterType, filterCategory]);

  const fetchStats = async () => {
    try {
      const res = await api.get('/api/knowledge/stats');
      setStats(res.data);
    } catch (err) {
      console.error('Error fetching stats:', err);
    }
  };

  useEffect(() => {
    if (isOpen) {
      fetchEntries();
      fetchStats();
    }
  }, [isOpen, fetchEntries]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    
    if (!formData.title.trim() || !formData.content.trim()) {
      toast.error('Title and content are required');
      return;
    }

    try {
      const payload = {
        ...formData,
        tags: formData.tags.split(',').map(t => t.trim()).filter(Boolean),
        confidence: parseInt(formData.confidence)
      };

      if (editingEntry) {
        await api.put(`/api/knowledge/${editingEntry.id}`, payload);
        toast.success('Entry updated');
      } else {
        await api.post('/api/knowledge', payload);
        toast.success('Entry added');
      }

      setShowAddForm(false);
      setEditingEntry(null);
      setFormData({
        title: '',
        content: '',
        type: 'note',
        category: 'general',
        tags: '',
        confidence: 80,
        source: 'user'
      });
      fetchEntries();
      fetchStats();
    } catch (err) {
      console.error('Error saving entry:', err);
      toast.error('Failed to save entry');
    }
  };

  const handleEdit = (entry) => {
    setFormData({
      title: entry.title,
      content: entry.content,
      type: entry.type,
      category: entry.category,
      tags: entry.tags?.join(', ') || '',
      confidence: entry.confidence,
      source: entry.source
    });
    setEditingEntry(entry);
    setShowAddForm(true);
  };

  const handleDelete = async (entryId) => {
    if (!window.confirm('Delete this entry?')) return;
    
    try {
      await api.delete(`/api/knowledge/${entryId}`);
      toast.success('Entry deleted');
      fetchEntries();
      fetchStats();
    } catch (err) {
      toast.error('Failed to delete entry');
    }
  };

  const getTypeIcon = (type) => {
    const typeConfig = TYPES.find(t => t.value === type);
    if (typeConfig) {
      const Icon = typeConfig.icon;
      return <Icon className={`w-4 h-4 ${typeConfig.color}`} />;
    }
    return <FileText className="w-4 h-4 text-zinc-400" />;
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black/80 z-50 flex items-center justify-center p-4">
      <div className="bg-zinc-900 border border-zinc-800 rounded-xl w-full max-w-4xl max-h-[85vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-zinc-800">
          <div className="flex items-center gap-3">
            <Brain className="w-6 h-6 text-purple-400" />
            <div>
              <h2 className="text-lg font-bold text-white">Knowledge Base</h2>
              <p className="text-xs text-zinc-500">
                {stats ? `${stats.total_entries} entries` : 'Loading...'}
              </p>
            </div>
          </div>
          <button onClick={onClose} className="p-2 hover:bg-zinc-800 rounded-lg">
            <X className="w-5 h-5 text-zinc-400" />
          </button>
        </div>

        {/* Search & Filters */}
        <div className="p-4 border-b border-zinc-800 space-y-3">
          <div className="flex gap-2">
            <div className="flex-1 relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-500" />
              <input
                type="text"
                placeholder="Search knowledge..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && fetchEntries()}
                className="w-full pl-10 pr-4 py-2 bg-zinc-800 border border-zinc-700 rounded-lg text-white text-sm focus:outline-none focus:border-purple-500"
              />
            </div>
            <button
              onClick={() => { setShowAddForm(true); setEditingEntry(null); }}
              className="px-4 py-2 bg-purple-500 text-white rounded-lg text-sm font-medium hover:bg-purple-600 flex items-center gap-2"
            >
              <Plus className="w-4 h-4" />
              Add
            </button>
          </div>
          
          <div className="flex gap-2 flex-wrap">
            <select
              value={filterType}
              onChange={(e) => setFilterType(e.target.value)}
              className="px-3 py-1.5 bg-zinc-800 border border-zinc-700 rounded text-sm text-white focus:outline-none"
            >
              <option value="">All Types</option>
              {TYPES.map(t => (
                <option key={t.value} value={t.value}>{t.label}</option>
              ))}
            </select>
            
            <select
              value={filterCategory}
              onChange={(e) => setFilterCategory(e.target.value)}
              className="px-3 py-1.5 bg-zinc-800 border border-zinc-700 rounded text-sm text-white focus:outline-none"
            >
              <option value="">All Categories</option>
              {CATEGORIES.map(c => (
                <option key={c} value={c}>{c.replace('_', ' ')}</option>
              ))}
            </select>
            
            <button
              onClick={fetchEntries}
              className="px-3 py-1.5 bg-zinc-800 border border-zinc-700 rounded text-sm text-white hover:bg-zinc-700"
            >
              Search
            </button>
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-4">
          {showAddForm ? (
            /* Add/Edit Form */
            <form onSubmit={handleSubmit} className="space-y-4">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-lg font-semibold text-white">
                  {editingEntry ? 'Edit Entry' : 'Add New Entry'}
                </h3>
                <button
                  type="button"
                  onClick={() => { setShowAddForm(false); setEditingEntry(null); }}
                  className="text-zinc-400 hover:text-white"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm text-zinc-400 mb-1">Title *</label>
                  <input
                    type="text"
                    value={formData.title}
                    onChange={(e) => setFormData({...formData, title: e.target.value})}
                    className="w-full px-3 py-2 bg-zinc-800 border border-zinc-700 rounded text-white text-sm focus:outline-none focus:border-purple-500"
                    placeholder="e.g., VWAP Bounce Strategy"
                  />
                </div>
                
                <div className="grid grid-cols-2 gap-2">
                  <div>
                    <label className="block text-sm text-zinc-400 mb-1">Type</label>
                    <select
                      value={formData.type}
                      onChange={(e) => setFormData({...formData, type: e.target.value})}
                      className="w-full px-3 py-2 bg-zinc-800 border border-zinc-700 rounded text-white text-sm focus:outline-none"
                    >
                      {TYPES.map(t => (
                        <option key={t.value} value={t.value}>{t.label}</option>
                      ))}
                    </select>
                  </div>
                  
                  <div>
                    <label className="block text-sm text-zinc-400 mb-1">Category</label>
                    <select
                      value={formData.category}
                      onChange={(e) => setFormData({...formData, category: e.target.value})}
                      className="w-full px-3 py-2 bg-zinc-800 border border-zinc-700 rounded text-white text-sm focus:outline-none"
                    >
                      {CATEGORIES.map(c => (
                        <option key={c} value={c}>{c.replace('_', ' ')}</option>
                      ))}
                    </select>
                  </div>
                </div>
              </div>

              <div>
                <label className="block text-sm text-zinc-400 mb-1">Content *</label>
                <textarea
                  value={formData.content}
                  onChange={(e) => setFormData({...formData, content: e.target.value})}
                  rows={6}
                  className="w-full px-3 py-2 bg-zinc-800 border border-zinc-700 rounded text-white text-sm focus:outline-none focus:border-purple-500"
                  placeholder="Describe the strategy, pattern, or insight in detail..."
                />
              </div>

              <div className="grid grid-cols-3 gap-4">
                <div>
                  <label className="block text-sm text-zinc-400 mb-1">Tags (comma-separated)</label>
                  <input
                    type="text"
                    value={formData.tags}
                    onChange={(e) => setFormData({...formData, tags: e.target.value})}
                    className="w-full px-3 py-2 bg-zinc-800 border border-zinc-700 rounded text-white text-sm focus:outline-none"
                    placeholder="momentum, breakout, high-volume"
                  />
                </div>
                
                <div>
                  <label className="block text-sm text-zinc-400 mb-1">Source</label>
                  <select
                    value={formData.source}
                    onChange={(e) => setFormData({...formData, source: e.target.value})}
                    className="w-full px-3 py-2 bg-zinc-800 border border-zinc-700 rounded text-white text-sm focus:outline-none"
                  >
                    <option value="user">User Input</option>
                    <option value="observation">Market Observation</option>
                    <option value="backtest">Backtest</option>
                    <option value="research">Research</option>
                  </select>
                </div>
                
                <div>
                  <label className="block text-sm text-zinc-400 mb-1">Confidence: {formData.confidence}%</label>
                  <input
                    type="range"
                    min="0"
                    max="100"
                    value={formData.confidence}
                    onChange={(e) => setFormData({...formData, confidence: e.target.value})}
                    className="w-full"
                  />
                </div>
              </div>

              <div className="flex justify-end gap-2 pt-4">
                <button
                  type="button"
                  onClick={() => { setShowAddForm(false); setEditingEntry(null); }}
                  className="px-4 py-2 bg-zinc-800 text-white rounded text-sm hover:bg-zinc-700"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="px-4 py-2 bg-purple-500 text-white rounded text-sm font-medium hover:bg-purple-600 flex items-center gap-2"
                >
                  <Save className="w-4 h-4" />
                  {editingEntry ? 'Update' : 'Save'}
                </button>
              </div>
            </form>
          ) : loading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="w-8 h-8 animate-spin text-purple-400" />
            </div>
          ) : entries.length === 0 ? (
            <div className="text-center py-12">
              <BookOpen className="w-12 h-12 text-zinc-600 mx-auto mb-4" />
              <p className="text-zinc-400">No entries found</p>
              <p className="text-sm text-zinc-500 mt-1">Add your first piece of trading knowledge</p>
            </div>
          ) : (
            /* Entry List */
            <div className="space-y-3">
              {entries.map((entry) => (
                <div
                  key={entry.id}
                  className="p-4 bg-zinc-800/50 border border-zinc-700/50 rounded-lg hover:border-zinc-600 transition-colors"
                >
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-2">
                        {getTypeIcon(entry.type)}
                        <h4 className="font-semibold text-white">{entry.title}</h4>
                        <span className="text-xs px-2 py-0.5 bg-zinc-700 rounded text-zinc-300">
                          {entry.category?.replace('_', ' ')}
                        </span>
                        <span className="text-xs text-zinc-500">
                          {entry.confidence}% confidence
                        </span>
                      </div>
                      
                      <p className="text-sm text-zinc-400 line-clamp-2 mb-2">
                        {entry.content}
                      </p>
                      
                      {entry.tags?.length > 0 && (
                        <div className="flex items-center gap-1 flex-wrap">
                          <Tag className="w-3 h-3 text-zinc-500" />
                          {entry.tags.map((tag, idx) => (
                            <span
                              key={idx}
                              className="text-xs px-1.5 py-0.5 bg-zinc-700/50 rounded text-zinc-400"
                            >
                              {tag}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                    
                    <div className="flex items-center gap-1">
                      <button
                        onClick={() => handleEdit(entry)}
                        className="p-1.5 hover:bg-zinc-700 rounded text-zinc-400 hover:text-white"
                        title="Edit"
                      >
                        <Edit2 className="w-4 h-4" />
                      </button>
                      <button
                        onClick={() => handleDelete(entry.id)}
                        className="p-1.5 hover:bg-zinc-700 rounded text-zinc-400 hover:text-red-400"
                        title="Delete"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Footer Stats */}
        {stats && !showAddForm && (
          <div className="p-3 border-t border-zinc-800 flex items-center gap-4 text-xs text-zinc-500">
            {Object.entries(stats.by_type || {}).filter(([_, count]) => count > 0).map(([type, count]) => (
              <span key={type} className="flex items-center gap-1">
                {getTypeIcon(type)}
                {count} {type === 'strategy' ? (count === 1 ? 'strategy' : 'strategies') : `${type}${count !== 1 ? 's' : ''}`}
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

export default KnowledgeBase;
