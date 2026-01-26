import React, { useState, useMemo } from 'react';
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
  ArrowLeft
} from 'lucide-react';
import glossaryData from '../data/glossaryData';

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

const GlossaryPage = () => {
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
              <h1 className="text-xl font-bold">Trading Glossary & Logic</h1>
            </div>
            <span className="text-sm text-zinc-500">
              {glossaryData.entries.length} terms documented
            </span>
          </div>
          
          {/* Search Bar */}
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
        </div>
      </div>

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
                Found {filteredEntries.length} result{filteredEntries.length !== 1 ? 's' : ''} for "{searchQuery}"
              </div>
            )}

            {/* Entries List */}
            {!selectedEntry && (
              <div className="space-y-3">
                {filteredEntries.length === 0 ? (
                  <Card>
                    <div className="text-center py-12">
                      <Search className="w-12 h-12 text-zinc-600 mx-auto mb-4" />
                      <p className="text-zinc-400">No terms found matching "{searchQuery}"</p>
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
