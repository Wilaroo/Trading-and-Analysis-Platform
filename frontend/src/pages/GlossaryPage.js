import React, { useState, useMemo, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Search,
  X,
  ChevronDown,
  ChevronRight,
  Target,
  TrendingUp,
  Zap,
  Activity,
  Briefcase,
  Shield,
  FileText,
  Globe,
  Calendar,
  Hash,
  BookOpen,
  ExternalLink,
  ArrowLeft,
  Brain,
  Plus,
  Tag,
  Lightbulb,
  CheckSquare,
  Edit2,
  Trash2,
  Save,
  Loader2
} from 'lucide-react';
import glossaryData from '../data/glossaryData';
import api from '../utils/api';
import { toast } from 'sonner';

// Knowledge Base Types
const KB_TYPES = [
  { value: 'strategy', label: 'Strategy', icon: Target, color: 'text-purple-400' },
  { value: 'pattern', label: 'Pattern', icon: TrendingUp, color: 'text-blue-400' },
  { value: 'insight', label: 'Insight', icon: Lightbulb, color: 'text-yellow-400' },
  { value: 'rule', label: 'Rule', icon: CheckSquare, color: 'text-green-400' },
  { value: 'note', label: 'Note', icon: FileText, color: 'text-zinc-400' },
  { value: 'indicator', label: 'Indicator', icon: TrendingUp, color: 'text-cyan-400' },
  { value: 'checklist', label: 'Checklist', icon: CheckSquare, color: 'text-orange-400' },
];

const KB_CATEGORIES = [
  'entry', 'exit', 'risk_management', 'position_sizing',
  'market_condition', 'technical', 'fundamental', 'sentiment',
  'premarket', 'intraday', 'swing', 'general'
];

// Icon mapping for categories
const categoryIcons = {
  'Target': Target,
  'TrendingUp': TrendingUp,
  'Zap': Zap,
  'Activity': Activity,
  'Briefcase': Briefcase,
  'Shield': Shield,
  'FileText': FileText,
  'Globe': Globe,
  'Calendar': Calendar,
  'Hash': Hash,
};

// Card component
const Card = ({ children, className = '' }) => (
  <div className={`bg-zinc-900/50 border border-white/5 rounded-xl p-4 backdrop-blur-sm ${className}`}>
    {children}
  </div>
);

// ===================== KNOWLEDGE BASE SECTION =====================
const KnowledgeBaseSection = () => {
  const [entries, setEntries] = useState([]);
  const [loading, setLoading] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [filterType, setFilterType] = useState('');
  const [filterCategory, setFilterCategory] = useState('');
  const [showAddForm, setShowAddForm] = useState(false);
  const [editingEntry, setEditingEntry] = useState(null);
  const [stats, setStats] = useState(null);
  
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
    fetchEntries();
    fetchStats();
  }, [fetchEntries]);

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
      
      resetForm();
      fetchEntries();
      fetchStats();
    } catch (err) {
      toast.error('Failed to save entry');
    }
  };

  const handleDelete = async (id) => {
    if (!window.confirm('Delete this entry?')) return;
    
    try {
      await api.delete(`/api/knowledge/${id}`);
      toast.success('Entry deleted');
      fetchEntries();
      fetchStats();
    } catch (err) {
      toast.error('Failed to delete entry');
    }
  };

  const resetForm = () => {
    setFormData({
      title: '',
      content: '',
      type: 'note',
      category: 'general',
      tags: '',
      confidence: 80,
      source: 'user'
    });
    setShowAddForm(false);
    setEditingEntry(null);
  };

  const startEdit = (entry) => {
    setEditingEntry(entry);
    setFormData({
      title: entry.title,
      content: entry.content,
      type: entry.type,
      category: entry.category,
      tags: entry.tags?.join(', ') || '',
      confidence: entry.confidence || 80,
      source: entry.source || 'user'
    });
    setShowAddForm(true);
  };

  const getTypeInfo = (type) => KB_TYPES.find(t => t.value === type) || KB_TYPES[4];

  return (
    <div className="space-y-6">
      {/* Stats Bar */}
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <Card>
            <div className="text-2xl font-bold text-cyan-400">{stats.total_entries || 0}</div>
            <div className="text-xs text-zinc-500">Total Entries</div>
          </Card>
          <Card>
            <div className="text-2xl font-bold text-purple-400">{stats.by_type?.strategy || 0}</div>
            <div className="text-xs text-zinc-500">Strategies</div>
          </Card>
          <Card>
            <div className="text-2xl font-bold text-green-400">{stats.by_type?.rule || 0}</div>
            <div className="text-xs text-zinc-500">Rules</div>
          </Card>
          <Card>
            <div className="text-2xl font-bold text-blue-400">{stats.by_type?.pattern || 0}</div>
            <div className="text-xs text-zinc-500">Patterns</div>
          </Card>
        </div>
      )}

      {/* Search & Filters */}
      <div className="flex flex-col md:flex-row gap-4">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-500" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search knowledge base..."
            className="w-full pl-10 pr-4 py-2 bg-zinc-900 border border-zinc-800 rounded-lg text-sm text-white placeholder-zinc-500 focus:outline-none focus:border-cyan-500/50"
          />
        </div>
        
        <select
          value={filterType}
          onChange={(e) => setFilterType(e.target.value)}
          className="px-3 py-2 bg-zinc-900 border border-zinc-800 rounded-lg text-sm text-white focus:outline-none focus:border-cyan-500/50"
        >
          <option value="">All Types</option>
          {KB_TYPES.map(t => (
            <option key={t.value} value={t.value}>{t.label}</option>
          ))}
        </select>
        
        <select
          value={filterCategory}
          onChange={(e) => setFilterCategory(e.target.value)}
          className="px-3 py-2 bg-zinc-900 border border-zinc-800 rounded-lg text-sm text-white focus:outline-none focus:border-cyan-500/50"
        >
          <option value="">All Categories</option>
          {KB_CATEGORIES.map(c => (
            <option key={c} value={c}>{c.replace('_', ' ').toUpperCase()}</option>
          ))}
        </select>
        
        <button
          onClick={() => setShowAddForm(true)}
          className="flex items-center gap-2 px-4 py-2 bg-cyan-600 hover:bg-cyan-500 rounded-lg text-sm font-medium transition-colors"
        >
          <Plus className="w-4 h-4" />
          Add Entry
        </button>
      </div>

      {/* Add/Edit Form */}
      <AnimatePresence>
        {showAddForm && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
          >
            <Card>
              <form onSubmit={handleSubmit} className="space-y-4">
                <div className="flex items-center justify-between mb-4">
                  <h3 className="text-lg font-semibold">
                    {editingEntry ? 'Edit Entry' : 'Add New Entry'}
                  </h3>
                  <button type="button" onClick={resetForm} className="text-zinc-500 hover:text-white">
                    <X className="w-5 h-5" />
                  </button>
                </div>
                
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <input
                    type="text"
                    value={formData.title}
                    onChange={(e) => setFormData({...formData, title: e.target.value})}
                    placeholder="Title"
                    className="px-3 py-2 bg-zinc-800 border border-zinc-700 rounded-lg text-white placeholder-zinc-500 focus:outline-none focus:border-cyan-500/50"
                  />
                  
                  <div className="flex gap-2">
                    <select
                      value={formData.type}
                      onChange={(e) => setFormData({...formData, type: e.target.value})}
                      className="flex-1 px-3 py-2 bg-zinc-800 border border-zinc-700 rounded-lg text-white focus:outline-none focus:border-cyan-500/50"
                    >
                      {KB_TYPES.map(t => (
                        <option key={t.value} value={t.value}>{t.label}</option>
                      ))}
                    </select>
                    
                    <select
                      value={formData.category}
                      onChange={(e) => setFormData({...formData, category: e.target.value})}
                      className="flex-1 px-3 py-2 bg-zinc-800 border border-zinc-700 rounded-lg text-white focus:outline-none focus:border-cyan-500/50"
                    >
                      {KB_CATEGORIES.map(c => (
                        <option key={c} value={c}>{c.replace('_', ' ')}</option>
                      ))}
                    </select>
                  </div>
                </div>
                
                <textarea
                  value={formData.content}
                  onChange={(e) => setFormData({...formData, content: e.target.value})}
                  placeholder="Content (supports markdown)"
                  rows={4}
                  className="w-full px-3 py-2 bg-zinc-800 border border-zinc-700 rounded-lg text-white placeholder-zinc-500 focus:outline-none focus:border-cyan-500/50 resize-none"
                />
                
                <div className="flex gap-4">
                  <input
                    type="text"
                    value={formData.tags}
                    onChange={(e) => setFormData({...formData, tags: e.target.value})}
                    placeholder="Tags (comma separated)"
                    className="flex-1 px-3 py-2 bg-zinc-800 border border-zinc-700 rounded-lg text-white placeholder-zinc-500 focus:outline-none focus:border-cyan-500/50"
                  />
                  
                  <div className="flex items-center gap-2">
                    <span className="text-sm text-zinc-500">Confidence:</span>
                    <input
                      type="number"
                      min="0"
                      max="100"
                      value={formData.confidence}
                      onChange={(e) => setFormData({...formData, confidence: e.target.value})}
                      className="w-20 px-2 py-2 bg-zinc-800 border border-zinc-700 rounded-lg text-white text-center focus:outline-none focus:border-cyan-500/50"
                    />
                  </div>
                </div>
                
                <div className="flex justify-end gap-2">
                  <button
                    type="button"
                    onClick={resetForm}
                    className="px-4 py-2 bg-zinc-800 hover:bg-zinc-700 rounded-lg text-sm transition-colors"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    className="flex items-center gap-2 px-4 py-2 bg-cyan-600 hover:bg-cyan-500 rounded-lg text-sm font-medium transition-colors"
                  >
                    <Save className="w-4 h-4" />
                    {editingEntry ? 'Update' : 'Save'}
                  </button>
                </div>
              </form>
            </Card>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Entries List */}
      {loading ? (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="w-8 h-8 text-cyan-400 animate-spin" />
        </div>
      ) : entries.length === 0 ? (
        <Card className="text-center py-12">
          <Brain className="w-12 h-12 text-zinc-700 mx-auto mb-4" />
          <p className="text-zinc-500">No entries found</p>
          <p className="text-sm text-zinc-600 mt-1">Add your trading knowledge, strategies, and rules</p>
        </Card>
      ) : (
        <div className="space-y-3">
          {entries.map(entry => {
            const typeInfo = getTypeInfo(entry.type);
            const TypeIcon = typeInfo.icon;
            
            return (
              <Card key={entry.id} className="hover:border-white/10 transition-colors">
                <div className="flex items-start gap-4">
                  <div className={`p-2 rounded-lg bg-zinc-800 ${typeInfo.color}`}>
                    <TypeIcon className="w-5 h-5" />
                  </div>
                  
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <h4 className="font-semibold text-white">{entry.title}</h4>
                      <span className={`text-xs px-2 py-0.5 rounded-full bg-zinc-800 ${typeInfo.color}`}>
                        {typeInfo.label}
                      </span>
                      <span className="text-xs px-2 py-0.5 rounded-full bg-zinc-800 text-zinc-400">
                        {entry.category?.replace('_', ' ')}
                      </span>
                    </div>
                    
                    <p className="text-sm text-zinc-400 line-clamp-2">{entry.content}</p>
                    
                    {entry.tags?.length > 0 && (
                      <div className="flex flex-wrap gap-1 mt-2">
                        {entry.tags.map((tag, i) => (
                          <span key={i} className="text-xs px-2 py-0.5 rounded bg-zinc-800 text-zinc-500">
                            #{tag}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                  
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-zinc-500">{entry.confidence}%</span>
                    <button
                      onClick={() => startEdit(entry)}
                      className="p-1.5 rounded hover:bg-zinc-800 text-zinc-500 hover:text-white transition-colors"
                    >
                      <Edit2 className="w-4 h-4" />
                    </button>
                    <button
                      onClick={() => handleDelete(entry.id)}
                      className="p-1.5 rounded hover:bg-zinc-800 text-zinc-500 hover:text-red-400 transition-colors"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                </div>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
};

// ===================== GLOSSARY PAGE =====================
const GlossaryPage = () => {
  const [activeTab, setActiveTab] = useState('glossary');
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedCategory, setSelectedCategory] = useState(null);
  const [selectedEntry, setSelectedEntry] = useState(null);
  const [expandedEntries, setExpandedEntries] = useState({});

  // Filter entries based on search and category
  const filteredEntries = useMemo(() => {
    let entries = glossaryData.entries;
    
    // Filter by category
    if (selectedCategory) {
      entries = entries.filter(e => e.category === selectedCategory);
    }
    
    // Filter by search query
    if (searchQuery.trim()) {
      const query = searchQuery.toLowerCase();
      entries = entries.filter(e => 
        e.term.toLowerCase().includes(query) ||
        e.shortDef.toLowerCase().includes(query) ||
        e.fullDef.toLowerCase().includes(query) ||
        e.tags?.some(t => t.toLowerCase().includes(query))
      );
    }
    
    return entries;
  }, [searchQuery, selectedCategory]);

  // Group entries by category for sidebar
  const entriesByCategory = useMemo(() => {
    const grouped = {};
    glossaryData.categories.forEach(cat => {
      grouped[cat.id] = glossaryData.entries.filter(e => e.category === cat.id);
    });
    return grouped;
  }, []);

  // Toggle entry expansion
  const toggleEntry = (entryId) => {
    setExpandedEntries(prev => ({
      ...prev,
      [entryId]: !prev[entryId]
    }));
  };

  // Open detailed view
  const openDetail = (entry) => {
    setSelectedEntry(entry);
  };

  // Find related entries
  const getRelatedEntries = (relatedTerms) => {
    if (!relatedTerms) return [];
    return glossaryData.entries.filter(e => relatedTerms.includes(e.id));
  };

  // Get category info
  const getCategoryInfo = (categoryId) => {
    return glossaryData.categories.find(c => c.id === categoryId);
  };

  return (
    <div className="min-h-screen bg-zinc-950 text-white">
      {/* Header */}
      <div className="sticky top-0 z-50 bg-zinc-950/95 backdrop-blur-sm border-b border-white/5">
        <div className="max-w-7xl mx-auto px-4 py-4">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-3">
              <BookOpen className="w-6 h-6 text-cyan-400" />
              <h1 className="text-xl font-bold">Trading Glossary & Knowledge</h1>
            </div>
            <span className="text-sm text-zinc-500">
              {activeTab === 'glossary' ? `${glossaryData.entries.length} terms` : 'Your trading knowledge'}
            </span>
          </div>
          
          {/* Tabs */}
          <div className="flex gap-2 mb-4">
            <button
              onClick={() => setActiveTab('glossary')}
              className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                activeTab === 'glossary'
                  ? 'bg-cyan-500/20 text-cyan-400 border border-cyan-500/30'
                  : 'bg-zinc-900 text-zinc-400 hover:text-white hover:bg-zinc-800'
              }`}
            >
              <BookOpen className="w-4 h-4" />
              Glossary
            </button>
            <button
              onClick={() => setActiveTab('knowledge')}
              className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                activeTab === 'knowledge'
                  ? 'bg-purple-500/20 text-purple-400 border border-purple-500/30'
                  : 'bg-zinc-900 text-zinc-400 hover:text-white hover:bg-zinc-800'
              }`}
            >
              <Brain className="w-4 h-4" />
              Knowledge Base
            </button>
          </div>
          
          {/* Search Bar - only show for glossary tab */}
          {activeTab === 'glossary' && (
            <div className="relative">
              <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-zinc-500" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search terms, definitions, or concepts..."
                className="w-full pl-12 pr-10 py-3 bg-zinc-900 border border-zinc-800 rounded-lg text-white placeholder-zinc-500 focus:outline-none focus:border-cyan-500/50 focus:ring-1 focus:ring-cyan-500/20"
                data-testid="glossary-search"
              />
              {searchQuery && (
                <button
                  onClick={() => setSearchQuery('')}
                  className="absolute right-4 top-1/2 -translate-y-1/2 text-zinc-500 hover:text-white"
                >
                  <X className="w-5 h-5" />
                </button>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Tab Content */}
      {activeTab === 'knowledge' ? (
        <div className="max-w-7xl mx-auto px-4 py-6">
          <KnowledgeBaseSection />
        </div>
      ) : (
        <div className="max-w-7xl mx-auto px-4 py-6">
          <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
          
          {/* Categories Sidebar */}
          <div className="lg:col-span-1">
            <Card className="sticky top-32">
              <h3 className="text-sm font-semibold uppercase tracking-wider text-zinc-400 mb-4">Categories</h3>
              
              <button
                onClick={() => setSelectedCategory(null)}
                className={`w-full flex items-center justify-between px-3 py-2 rounded-lg mb-2 transition-colors ${
                  !selectedCategory 
                    ? 'bg-cyan-500/20 text-cyan-400 border border-cyan-500/30' 
                    : 'hover:bg-zinc-800 text-zinc-400'
                }`}
              >
                <span className="flex items-center gap-2">
                  <BookOpen className="w-4 h-4" />
                  All Terms
                </span>
                <span className="text-xs">{glossaryData.entries.length}</span>
              </button>
              
              {glossaryData.categories.map(category => {
                const IconComponent = categoryIcons[category.icon] || Hash;
                const count = entriesByCategory[category.id]?.length || 0;
                
                return (
                  <button
                    key={category.id}
                    onClick={() => setSelectedCategory(category.id)}
                    className={`w-full flex items-center justify-between px-3 py-2 rounded-lg mb-1 transition-colors ${
                      selectedCategory === category.id 
                        ? 'bg-cyan-500/20 text-cyan-400 border border-cyan-500/30' 
                        : 'hover:bg-zinc-800 text-zinc-400'
                    }`}
                    data-testid={`category-${category.id}`}
                  >
                    <span className="flex items-center gap-2">
                      <IconComponent className="w-4 h-4" />
                      <span className="text-sm">{category.name}</span>
                    </span>
                    <span className="text-xs">{count}</span>
                  </button>
                );
              })}
            </Card>
          </div>

          {/* Main Content */}
          <div className="lg:col-span-3">
            {/* Selected Entry Detail View */}
            <AnimatePresence>
              {selectedEntry && (
                <motion.div
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -20 }}
                  className="mb-6"
                >
                  <Card>
                    <button
                      onClick={() => setSelectedEntry(null)}
                      className="flex items-center gap-2 text-cyan-400 hover:text-cyan-300 mb-4"
                    >
                      <ArrowLeft className="w-4 h-4" />
                      Back to list
                    </button>
                    
                    <div className="flex items-start justify-between mb-4">
                      <div>
                        <h2 className="text-2xl font-bold text-white mb-1">{selectedEntry.term}</h2>
                        <div className="flex items-center gap-2">
                          <span className="text-xs px-2 py-1 bg-cyan-500/20 text-cyan-400 rounded">
                            {getCategoryInfo(selectedEntry.category)?.name}
                          </span>
                          {selectedEntry.tags?.map((tag, i) => (
                            <span key={i} className="text-xs px-2 py-0.5 bg-zinc-800 text-zinc-400 rounded">
                              #{tag}
                            </span>
                          ))}
                        </div>
                      </div>
                    </div>
                    
                    <p className="text-lg text-cyan-300 mb-4 border-l-2 border-cyan-500 pl-4">
                      {selectedEntry.shortDef}
                    </p>
                    
                    <div className="prose prose-invert max-w-none">
                      <div className="bg-zinc-800/50 rounded-lg p-4 whitespace-pre-wrap text-sm text-zinc-300 leading-relaxed">
                        {selectedEntry.fullDef}
                      </div>
                    </div>
                    
                    {/* Related Terms */}
                    {selectedEntry.relatedTerms?.length > 0 && (
                      <div className="mt-6 pt-4 border-t border-white/5">
                        <h4 className="text-sm font-semibold text-zinc-400 mb-3">Related Terms</h4>
                        <div className="flex flex-wrap gap-2">
                          {getRelatedEntries(selectedEntry.relatedTerms).map(related => (
                            <button
                              key={related.id}
                              onClick={() => setSelectedEntry(related)}
                              className="flex items-center gap-1 px-3 py-1.5 bg-zinc-800 hover:bg-zinc-700 rounded-lg text-sm transition-colors"
                            >
                              <ExternalLink className="w-3 h-3" />
                              {related.term}
                            </button>
                          ))}
                        </div>
                      </div>
                    )}
                  </Card>
                </motion.div>
              )}
            </AnimatePresence>

            {/* Search Results Info */}
            {searchQuery && (
              <div className="mb-4 text-sm text-zinc-400">
                Found {filteredEntries.length} result{filteredEntries.length !== 1 ? 's' : ''} for &ldquo;{searchQuery}&rdquo;
              </div>
            )}

            {/* Entries List */}
            {!selectedEntry && (
              <div className="space-y-3">
                {filteredEntries.length === 0 ? (
                  <Card>
                    <div className="text-center py-12">
                      <Search className="w-12 h-12 text-zinc-600 mx-auto mb-4" />
                      <p className="text-zinc-400">No terms found matching &ldquo;{searchQuery}&rdquo;</p>
                      <p className="text-zinc-500 text-sm mt-2">Try a different search term</p>
                    </div>
                  </Card>
                ) : (
                  filteredEntries.map(entry => {
                    const isExpanded = expandedEntries[entry.id];
                    const category = getCategoryInfo(entry.category);
                    const IconComponent = categoryIcons[category?.icon] || Hash;
                    
                    return (
                      <Card 
                        key={entry.id}
                        className="hover:border-cyan-500/20 transition-colors cursor-pointer"
                      >
                        <div 
                          className="flex items-start justify-between"
                          onClick={() => toggleEntry(entry.id)}
                        >
                          <div className="flex-1">
                            <div className="flex items-center gap-2 mb-1">
                              <IconComponent className="w-4 h-4 text-cyan-400" />
                              <h3 className="font-semibold text-white">{entry.term}</h3>
                              <span className="text-[10px] px-1.5 py-0.5 bg-zinc-800 text-zinc-500 rounded">
                                {category?.name}
                              </span>
                            </div>
                            <p className="text-sm text-zinc-400">{entry.shortDef}</p>
                          </div>
                          <button className="ml-4 text-zinc-500">
                            {isExpanded ? (
                              <ChevronDown className="w-5 h-5" />
                            ) : (
                              <ChevronRight className="w-5 h-5" />
                            )}
                          </button>
                        </div>
                        
                        <AnimatePresence>
                          {isExpanded && (
                            <motion.div
                              initial={{ height: 0, opacity: 0 }}
                              animate={{ height: 'auto', opacity: 1 }}
                              exit={{ height: 0, opacity: 0 }}
                              transition={{ duration: 0.2 }}
                              className="overflow-hidden"
                            >
                              <div className="mt-4 pt-4 border-t border-white/5">
                                <div className="bg-zinc-800/50 rounded-lg p-4 whitespace-pre-wrap text-sm text-zinc-300 leading-relaxed max-h-80 overflow-y-auto">
                                  {entry.fullDef}
                                </div>
                                
                                <div className="flex items-center justify-between mt-4">
                                  <div className="flex flex-wrap gap-1">
                                    {entry.tags?.slice(0, 5).map((tag, i) => (
                                      <span 
                                        key={i} 
                                        className="text-[10px] px-1.5 py-0.5 bg-zinc-800 text-zinc-500 rounded cursor-pointer hover:bg-zinc-700"
                                        onClick={(e) => { e.stopPropagation(); setSearchQuery(tag); }}
                                      >
                                        #{tag}
                                      </span>
                                    ))}
                                  </div>
                                  
                                  <button
                                    onClick={(e) => { e.stopPropagation(); openDetail(entry); }}
                                    className="flex items-center gap-1 text-xs text-cyan-400 hover:text-cyan-300"
                                  >
                                    View full details
                                    <ExternalLink className="w-3 h-3" />
                                  </button>
                                </div>
                                
                                {/* Quick related terms */}
                                {entry.relatedTerms?.length > 0 && (
                                  <div className="mt-3 pt-3 border-t border-white/5">
                                    <span className="text-[10px] text-zinc-500 uppercase">Related: </span>
                                    {getRelatedEntries(entry.relatedTerms).slice(0, 4).map((related, i) => (
                                      <button
                                        key={related.id}
                                        onClick={(e) => { e.stopPropagation(); openDetail(related); }}
                                        className="text-xs text-cyan-400 hover:underline ml-2"
                                      >
                                        {related.term}{i < Math.min(entry.relatedTerms.length, 4) - 1 ? ',' : ''}
                                      </button>
                                    ))}
                                  </div>
                                )}
                              </div>
                            </motion.div>
                          )}
                        </AnimatePresence>
                      </Card>
                    );
                  })
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

export default GlossaryPage;
