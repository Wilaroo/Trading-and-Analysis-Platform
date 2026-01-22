import React, { useState, useEffect } from 'react';
import { Newspaper, RefreshCw, Sparkles, TrendingUp, TrendingDown } from 'lucide-react';
import api from '../utils/api';

const Card = ({ children, className = '', hover = true }) => (
  <div className={`bg-paper rounded-lg p-4 border border-white/10 ${
    hover ? 'transition-all duration-200 hover:border-primary/30' : ''
  } ${className}`}>
    {children}
  </div>
);

const PriceDisplay = ({ value, className = '' }) => {
  const isPositive = value > 0;
  const isNeutral = value === 0;
  
  return (
    <span className={`font-mono-data flex items-center gap-1 ${
      isNeutral ? 'text-zinc-400' : isPositive ? 'text-green-400' : 'text-red-400'
    } ${className}`}>
      {isPositive ? <TrendingUp className="w-4 h-4" /> : <TrendingDown className="w-4 h-4" />}
      {isPositive ? '+' : ''}{value?.toFixed(2)}%
    </span>
  );
};

// ===================== NEWSLETTER PAGE =====================
const NewsletterPage = () => {
  const [newsletter, setNewsletter] = useState(null);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);

  const loadNewsletter = async () => {
    setLoading(true);
    try {
      const res = await api.get('/api/newsletter/latest');
      setNewsletter(res.data);
    } catch (err) { console.error('Failed to load newsletter:', err); }
    finally { setLoading(false); }
  };

  const generateNewsletter = async () => {
    setGenerating(true);
    try {
      const res = await api.post('/api/newsletter/generate');
      setNewsletter(res.data);
    } catch (err) { console.error('Failed to generate newsletter:', err); }
    finally { setGenerating(false); }
  };

  useEffect(() => { loadNewsletter(); }, []);

  return (
    <div className="space-y-6 animate-fade-in" data-testid="newsletter-page">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Newspaper className="w-6 h-6 text-primary" />
            Morning Newsletter
          </h1>
          <p className="text-zinc-500 text-sm">AI-generated daily market briefing</p>
        </div>
        <button
          onClick={generateNewsletter}
          disabled={generating}
          className="btn-primary flex items-center gap-2"
          data-testid="generate-newsletter-btn"
        >
          {generating ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
          {generating ? 'Generating...' : 'Generate'}
        </button>
      </div>

      {loading ? (
        <Card hover={false} className="animate-pulse">
          <div className="h-8 bg-white/5 rounded w-1/3 mb-4"></div>
          <div className="h-4 bg-white/5 rounded w-full mb-2"></div>
          <div className="h-4 bg-white/5 rounded w-3/4"></div>
        </Card>
      ) : newsletter ? (
        <div className="space-y-6">
          {/* Header */}
          <Card hover={false} className="bg-gradient-to-br from-primary/10 to-accent/10">
            <div className="flex items-center gap-2 mb-2">
              <Sparkles className="w-5 h-5 text-primary" />
              <span className="text-xs text-primary uppercase tracking-wider">AI Generated</span>
            </div>
            <h2 className="text-xl font-bold mb-2">{newsletter.title}</h2>
            <p className="text-zinc-400 text-sm">
              {newsletter.date ? new Date(newsletter.date).toLocaleDateString('en-US', { 
                weekday: 'long', 
                year: 'numeric', 
                month: 'long', 
                day: 'numeric' 
              }) : 'Today'}
            </p>
          </Card>

          {/* Market Outlook */}
          {newsletter.market_outlook && (
            <Card hover={false}>
              <h3 className="font-semibold mb-4">Market Outlook</h3>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
                <div className="bg-white/5 rounded-lg p-3">
                  <p className="text-xs text-zinc-500 uppercase">Overall Sentiment</p>
                  <p className={`text-lg font-semibold ${
                    newsletter.market_outlook.sentiment === 'bullish' ? 'text-green-400' :
                    newsletter.market_outlook.sentiment === 'bearish' ? 'text-red-400' :
                    'text-yellow-400'
                  }`}>
                    {newsletter.market_outlook.sentiment?.toUpperCase()}
                  </p>
                </div>
                <div className="bg-white/5 rounded-lg p-3">
                  <p className="text-xs text-zinc-500 uppercase">Key Levels</p>
                  <p className="text-sm text-zinc-300">{newsletter.market_outlook.key_levels}</p>
                </div>
                <div className="bg-white/5 rounded-lg p-3">
                  <p className="text-xs text-zinc-500 uppercase">Focus</p>
                  <p className="text-sm text-zinc-300">{newsletter.market_outlook.focus}</p>
                </div>
              </div>
              <p className="text-zinc-300">{newsletter.summary}</p>
            </Card>
          )}

          {/* Top Stories */}
          {newsletter.top_stories && newsletter.top_stories.length > 0 && (
            <Card hover={false}>
              <h3 className="font-semibold mb-4">Top Stories</h3>
              <div className="space-y-4">
                {newsletter.top_stories.map((story, idx) => (
                  <div key={idx} className="border-b border-white/5 pb-4 last:border-0 last:pb-0">
                    <h4 className="font-medium text-white mb-1">{story.headline}</h4>
                    <p className="text-sm text-zinc-400">{story.summary}</p>
                    {story.impact && (
                      <span className={`inline-block mt-2 text-xs badge ${
                        story.impact === 'positive' ? 'bg-green-500/20 text-green-400' :
                        story.impact === 'negative' ? 'bg-red-500/20 text-red-400' :
                        'bg-zinc-500/20 text-zinc-400'
                      }`}>
                        {story.impact} impact
                      </span>
                    )}
                  </div>
                ))}
              </div>
            </Card>
          )}

          {/* Watchlist */}
          {newsletter.watchlist && newsletter.watchlist.length > 0 && (
            <Card hover={false}>
              <h3 className="font-semibold mb-4">Today's Watchlist</h3>
              <div className="overflow-x-auto">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Rank</th>
                      <th>Symbol</th>
                      <th>Score</th>
                      <th>Reason</th>
                    </tr>
                  </thead>
                  <tbody>
                    {newsletter.watchlist.map((item, idx) => (
                      <tr key={idx}>
                        <td className="text-zinc-500">#{idx + 1}</td>
                        <td className="font-bold text-primary">{item.symbol}</td>
                        <td>
                          <div className="flex items-center gap-2">
                            <div className="w-12 h-2 bg-white/10 rounded-full overflow-hidden">
                              <div 
                                className={`h-full rounded-full ${
                                  item.score >= 70 ? 'bg-green-400' : 
                                  item.score >= 50 ? 'bg-yellow-400' : 
                                  'bg-blue-400'
                                }`} 
                                style={{ width: `${item.score}%` }} 
                              />
                            </div>
                            <span className="text-sm">{item.score}</span>
                          </div>
                        </td>
                        <td className="text-sm text-zinc-400">{item.reason}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          )}
        </div>
      ) : (
        <Card hover={false}>
          <div className="text-center py-12">
            <Newspaper className="w-12 h-12 text-zinc-600 mx-auto mb-4" />
            <p className="text-zinc-500">No newsletter available</p>
            <p className="text-zinc-600 text-sm mt-1">Click "Generate" to create today's briefing</p>
          </div>
        </Card>
      )}
    </div>
  );
};

export default NewsletterPage;
