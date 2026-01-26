import React, { useState, useEffect } from 'react';
import { 
  Newspaper, RefreshCw, Sparkles, TrendingUp, TrendingDown, 
  Target, AlertTriangle, Calendar, ChevronRight, Clock,
  ArrowUpRight, ArrowDownRight, Minus, Zap, Shield, Eye
} from 'lucide-react';
import api from '../utils/api';

const Card = ({ children, className = '', hover = true }) => (
  <div className={`bg-paper rounded-lg p-4 border border-white/10 ${
    hover ? 'transition-all duration-200 hover:border-primary/30' : ''
  } ${className}`}>
    {children}
  </div>
);

const SentimentBadge = ({ sentiment }) => {
  const config = {
    bullish: { bg: 'bg-green-500/20', text: 'text-green-400', icon: TrendingUp, label: 'BULLISH' },
    bearish: { bg: 'bg-red-500/20', text: 'text-red-400', icon: TrendingDown, label: 'BEARISH' },
    neutral: { bg: 'bg-yellow-500/20', text: 'text-yellow-400', icon: Minus, label: 'NEUTRAL' }
  };
  
  const { bg, text, icon: Icon, label } = config[sentiment?.toLowerCase()] || config.neutral;
  
  return (
    <span className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full ${bg} ${text} text-sm font-semibold`}>
      <Icon className="w-4 h-4" />
      {label}
    </span>
  );
};

const OpportunityCard = ({ opportunity, index }) => {
  const isLong = opportunity.direction?.toUpperCase() === 'LONG';
  const isShort = opportunity.direction?.toUpperCase() === 'SHORT';
  
  return (
    <div className={`p-4 rounded-lg border ${
      isLong ? 'border-green-500/30 bg-green-500/5' : 
      isShort ? 'border-red-500/30 bg-red-500/5' : 
      'border-white/10 bg-white/5'
    }`}>
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <span className="text-xs text-zinc-500">#{index + 1}</span>
          <span className="font-bold text-lg">{opportunity.symbol}</span>
          {isLong && <ArrowUpRight className="w-4 h-4 text-green-400" />}
          {isShort && <ArrowDownRight className="w-4 h-4 text-red-400" />}
        </div>
        <span className={`text-sm font-semibold px-2 py-0.5 rounded ${
          isLong ? 'bg-green-500/20 text-green-400' : 
          isShort ? 'bg-red-500/20 text-red-400' : 
          'bg-zinc-500/20 text-zinc-400'
        }`}>
          {opportunity.direction || 'WATCH'}
        </span>
      </div>
      
      <p className="text-sm text-zinc-400 mb-3">{opportunity.reasoning || opportunity.reason}</p>
      
      {(opportunity.entry || opportunity.target || opportunity.stop) && (
        <div className="grid grid-cols-3 gap-2 text-xs">
          {opportunity.entry && (
            <div className="bg-white/5 rounded p-2">
              <span className="text-zinc-500 block">Entry</span>
              <span className="text-white font-mono">${opportunity.entry}</span>
            </div>
          )}
          {opportunity.target && (
            <div className="bg-green-500/10 rounded p-2">
              <span className="text-zinc-500 block">Target</span>
              <span className="text-green-400 font-mono">${opportunity.target}</span>
            </div>
          )}
          {opportunity.stop && (
            <div className="bg-red-500/10 rounded p-2">
              <span className="text-zinc-500 block">Stop</span>
              <span className="text-red-400 font-mono">${opportunity.stop}</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

const NewsletterPage = () => {
  const [newsletter, setNewsletter] = useState(null);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState(null);

  const loadNewsletter = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.get('/api/newsletter/latest');
      setNewsletter(res.data);
    } catch (err) { 
      console.error('Failed to load newsletter:', err);
      setError('Failed to load newsletter');
    }
    finally { setLoading(false); }
  };

  const generateNewsletter = async () => {
    setGenerating(true);
    setError(null);
    try {
      const res = await api.post('/api/newsletter/generate', {
        include_scanner_data: true
      });
      setNewsletter(res.data);
    } catch (err) { 
      console.error('Failed to generate newsletter:', err);
      setError(err.response?.data?.detail || 'Failed to generate newsletter');
    }
    finally { setGenerating(false); }
  };

  useEffect(() => { loadNewsletter(); }, []);

  const formatDate = (dateStr) => {
    if (!dateStr) return 'Today';
    try {
      return new Date(dateStr).toLocaleDateString('en-US', { 
        weekday: 'long', 
        year: 'numeric', 
        month: 'long', 
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
      });
    } catch {
      return dateStr;
    }
  };

  return (
    <div className="space-y-6 animate-fade-in" data-testid="newsletter-page">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Newspaper className="w-6 h-6 text-primary" />
            Premarket Briefing
          </h1>
          <p className="text-zinc-500 text-sm">AI-powered daytrader's morning newsletter</p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={loadNewsletter}
            disabled={loading}
            className="btn-secondary flex items-center gap-2"
            data-testid="refresh-newsletter-btn"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          </button>
          <button
            onClick={generateNewsletter}
            disabled={generating}
            className="btn-primary flex items-center gap-2"
            data-testid="generate-newsletter-btn"
          >
            {generating ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
            {generating ? 'Generating...' : 'Generate Briefing'}
          </button>
        </div>
      </div>

      {/* Error Alert */}
      {error && (
        <Card hover={false} className="border-red-500/30 bg-red-500/5">
          <div className="flex items-center gap-2 text-red-400">
            <AlertTriangle className="w-5 h-5" />
            <span>{error}</span>
          </div>
        </Card>
      )}

      {/* Loading State */}
      {loading ? (
        <div className="grid gap-4">
          <Card hover={false} className="animate-pulse">
            <div className="h-8 bg-white/5 rounded w-1/3 mb-4"></div>
            <div className="h-4 bg-white/5 rounded w-full mb-2"></div>
            <div className="h-4 bg-white/5 rounded w-3/4"></div>
          </Card>
        </div>
      ) : newsletter ? (
        <div className="space-y-6">
          
          {/* Header Card with Sentiment */}
          <Card hover={false} className="bg-gradient-to-br from-primary/10 to-accent/10 border-primary/20">
            <div className="flex items-start justify-between mb-4">
              <div>
                <div className="flex items-center gap-2 mb-2">
                  <Sparkles className="w-5 h-5 text-primary" />
                  <span className="text-xs text-primary uppercase tracking-wider font-semibold">AI Generated</span>
                </div>
                <h2 className="text-xl font-bold mb-1">{newsletter.title || 'Premarket Briefing'}</h2>
                <p className="text-zinc-400 text-sm flex items-center gap-1">
                  <Clock className="w-3.5 h-3.5" />
                  {formatDate(newsletter.date || newsletter.generated_at)}
                </p>
              </div>
              {newsletter.market_outlook?.sentiment && (
                <SentimentBadge sentiment={newsletter.market_outlook.sentiment} />
              )}
            </div>
            
            {newsletter.market_outlook?.explanation && (
              <p className="text-zinc-300 text-sm">{newsletter.market_outlook.explanation}</p>
            )}
          </Card>

          {/* Grid Layout for Key Sections */}
          <div className="grid md:grid-cols-2 gap-4">
            
            {/* Overnight Recap */}
            <Card hover={false}>
              <div className="flex items-center gap-2 mb-3">
                <Eye className="w-5 h-5 text-blue-400" />
                <h3 className="font-semibold">Overnight Recap</h3>
              </div>
              <p className="text-zinc-300 text-sm leading-relaxed">
                {newsletter.summary || 'Generate a briefing to see overnight market activity.'}
              </p>
            </Card>

            {/* Key Levels */}
            <Card hover={false}>
              <div className="flex items-center gap-2 mb-3">
                <Target className="w-5 h-5 text-cyan-400" />
                <h3 className="font-semibold">Key Levels</h3>
              </div>
              {newsletter.market_outlook?.key_levels ? (
                typeof newsletter.market_outlook.key_levels === 'object' ? (
                  <div className="space-y-2">
                    {Object.entries(newsletter.market_outlook.key_levels).map(([symbol, levels]) => (
                      <div key={symbol} className="flex items-center justify-between text-sm">
                        <span className="font-semibold text-primary">{symbol}</span>
                        <span className="text-zinc-400">
                          S: {levels.support || 'N/A'} | R: {levels.resistance || 'N/A'}
                        </span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-zinc-300 text-sm">{newsletter.market_outlook.key_levels}</p>
                )
              ) : (
                <p className="text-zinc-500 text-sm">Generate briefing for key levels</p>
              )}
            </Card>
          </div>

          {/* Trade Opportunities */}
          {newsletter.opportunities && newsletter.opportunities.length > 0 && (
            <Card hover={false}>
              <div className="flex items-center gap-2 mb-4">
                <Zap className="w-5 h-5 text-yellow-400" />
                <h3 className="font-semibold">Trade Opportunities</h3>
                <span className="text-xs text-zinc-500 ml-auto">{newsletter.opportunities.length} setups</span>
              </div>
              <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-3">
                {newsletter.opportunities.map((opp, idx) => (
                  <OpportunityCard key={idx} opportunity={opp} index={idx} />
                ))}
              </div>
            </Card>
          )}

          {/* Catalyst Watch / Top Stories */}
          {newsletter.top_stories && newsletter.top_stories.length > 0 && (
            <Card hover={false}>
              <div className="flex items-center gap-2 mb-4">
                <Calendar className="w-5 h-5 text-purple-400" />
                <h3 className="font-semibold">Catalyst Watch</h3>
              </div>
              <div className="space-y-3">
                {newsletter.top_stories.map((story, idx) => (
                  <div key={idx} className="flex items-start gap-3 p-3 bg-white/5 rounded-lg">
                    <ChevronRight className="w-4 h-4 text-zinc-500 mt-0.5 flex-shrink-0" />
                    <div>
                      <p className="text-sm font-medium text-white">{story.headline}</p>
                      {story.summary && (
                        <p className="text-xs text-zinc-400 mt-1">{story.summary}</p>
                      )}
                      {story.impact && (
                        <span className={`inline-block mt-2 text-xs px-2 py-0.5 rounded ${
                          story.impact === 'positive' ? 'bg-green-500/20 text-green-400' :
                          story.impact === 'negative' ? 'bg-red-500/20 text-red-400' :
                          'bg-zinc-500/20 text-zinc-400'
                        }`}>
                          {story.impact} impact
                        </span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </Card>
          )}

          {/* Risk Factors */}
          {newsletter.risk_factors && newsletter.risk_factors.length > 0 && (
            <Card hover={false} className="border-red-500/20">
              <div className="flex items-center gap-2 mb-3">
                <Shield className="w-5 h-5 text-red-400" />
                <h3 className="font-semibold">Risk Factors</h3>
              </div>
              <ul className="space-y-2">
                {newsletter.risk_factors.map((risk, idx) => (
                  <li key={idx} className="flex items-start gap-2 text-sm text-zinc-300">
                    <AlertTriangle className="w-4 h-4 text-red-400 mt-0.5 flex-shrink-0" />
                    <span>{risk}</span>
                  </li>
                ))}
              </ul>
            </Card>
          )}

          {/* Game Plan */}
          {newsletter.game_plan && (
            <Card hover={false} className="bg-gradient-to-r from-primary/5 to-transparent border-primary/20">
              <div className="flex items-center gap-2 mb-3">
                <Target className="w-5 h-5 text-primary" />
                <h3 className="font-semibold">Today's Game Plan</h3>
              </div>
              <div className="text-sm text-zinc-300 whitespace-pre-wrap leading-relaxed">
                {newsletter.game_plan}
              </div>
            </Card>
          )}

          {/* Watchlist Table */}
          {newsletter.watchlist && newsletter.watchlist.length > 0 && (
            <Card hover={false}>
              <div className="flex items-center gap-2 mb-4">
                <Eye className="w-5 h-5 text-cyan-400" />
                <h3 className="font-semibold">Watchlist</h3>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-zinc-500 border-b border-white/10">
                      <th className="pb-2 font-medium">#</th>
                      <th className="pb-2 font-medium">Symbol</th>
                      <th className="pb-2 font-medium">Direction</th>
                      <th className="pb-2 font-medium">Score</th>
                      <th className="pb-2 font-medium">Reason</th>
                    </tr>
                  </thead>
                  <tbody>
                    {newsletter.watchlist.map((item, idx) => (
                      <tr key={idx} className="border-b border-white/5">
                        <td className="py-3 text-zinc-500">{idx + 1}</td>
                        <td className="py-3 font-bold text-primary">{item.symbol}</td>
                        <td className="py-3">
                          <span className={`text-xs px-2 py-0.5 rounded ${
                            item.direction === 'LONG' ? 'bg-green-500/20 text-green-400' :
                            item.direction === 'SHORT' ? 'bg-red-500/20 text-red-400' :
                            'bg-zinc-500/20 text-zinc-400'
                          }`}>
                            {item.direction || 'WATCH'}
                          </span>
                        </td>
                        <td className="py-3">
                          <div className="flex items-center gap-2">
                            <div className="w-12 h-2 bg-white/10 rounded-full overflow-hidden">
                              <div 
                                className={`h-full rounded-full ${
                                  item.score >= 70 ? 'bg-green-400' : 
                                  item.score >= 50 ? 'bg-yellow-400' : 
                                  'bg-blue-400'
                                }`} 
                                style={{ width: `${item.score || 50}%` }} 
                              />
                            </div>
                            <span className="text-zinc-400">{item.score || '-'}</span>
                          </div>
                        </td>
                        <td className="py-3 text-zinc-400 max-w-xs truncate">{item.reason}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          )}
          
        </div>
      ) : (
        /* Empty State */
        <Card hover={false} className="border-dashed">
          <div className="text-center py-12">
            <Newspaper className="w-16 h-16 text-zinc-600 mx-auto mb-4" />
            <h3 className="text-xl font-semibold mb-2">No Briefing Yet</h3>
            <p className="text-zinc-500 mb-6 max-w-md mx-auto">
              Click "Generate Briefing" to create your personalized premarket analysis with AI-powered insights, trade opportunities, and key levels.
            </p>
            <button
              onClick={generateNewsletter}
              disabled={generating}
              className="btn-primary inline-flex items-center gap-2"
            >
              {generating ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
              {generating ? 'Generating...' : 'Generate Briefing'}
            </button>
          </div>
        </Card>
      )}

      {/* Setup Instructions */}
      <Card hover={false} className="bg-zinc-900/50">
        <h4 className="font-semibold mb-2 flex items-center gap-2">
          <AlertTriangle className="w-4 h-4 text-yellow-400" />
          Setup Notes
        </h4>
        <ul className="text-sm text-zinc-400 space-y-1">
          <li>• Connect to IB Gateway for real-time market data integration</li>
          <li>• Configure PERPLEXITY_API_KEY in backend/.env for AI-powered analysis</li>
          <li>• Newsletter uses Perplexity's Sonar model for real-time market intelligence</li>
        </ul>
      </Card>
    </div>
  );
};

export default NewsletterPage;
