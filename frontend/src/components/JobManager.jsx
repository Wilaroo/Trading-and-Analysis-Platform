/**
 * JobManager - UI for creating and monitoring background jobs
 * 
 * Integrates with:
 * - Focus Mode system (automatically sets appropriate mode)
 * - Worker process (executes jobs in background)
 * - Job Queue (MongoDB-based queue)
 * - Browser Notifications (alerts when jobs complete)
 * 
 * Job Types:
 * - Data Collection: Collect historical data from IB
 * - Backtesting: Run strategy simulations
 * - AI Training: Train models (handled in UnifiedAITraining)
 */

import React, { useState, useEffect, useCallback, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { 
  Database, 
  Play, 
  Pause, 
  X, 
  ChevronDown, 
  ChevronUp,
  Clock,
  CheckCircle,
  XCircle,
  AlertCircle,
  RefreshCw,
  Loader2,
  TrendingUp,
  Calendar,
  BarChart3,
  Activity,
  Bell,
  BellOff
} from 'lucide-react';
import { toast } from 'sonner';
import { safePolling } from '../utils/safePolling';
import api from '../utils/api';
import { useFocusMode } from '../contexts/FocusModeContext';

// ===================== NOTIFICATION HELPERS =====================

/**
 * Request browser notification permission
 */
const requestNotificationPermission = async () => {
  if (!('Notification' in window)) {
    console.log('Browser does not support notifications');
    return false;
  }
  
  if (Notification.permission === 'granted') {
    return true;
  }
  
  if (Notification.permission !== 'denied') {
    const permission = await Notification.requestPermission();
    return permission === 'granted';
  }
  
  return false;
};

/**
 * Show a browser notification
 */
const showBrowserNotification = (title, body, icon = '✅') => {
  if (!('Notification' in window) || Notification.permission !== 'granted') {
    return;
  }
  
  try {
    const notification = new Notification(title, {
      body,
      icon: '/favicon.ico',
      badge: '/favicon.ico',
      tag: 'sentcom-job-notification',
      requireInteraction: false,
      silent: false
    });
    
    // Auto-close after 10 seconds
    setTimeout(() => notification.close(), 10000);
    
    // Focus window when clicked
    notification.onclick = () => {
      window.focus();
      notification.close();
    };
  } catch (e) {
    console.error('Failed to show notification:', e);
  }
};

/**
 * Play a notification sound
 */
const playNotificationSound = (type = 'success') => {
  try {
    // Use Web Audio API for a simple beep
    const audioContext = new (window.AudioContext || window.webkitAudioContext)();
    const oscillator = audioContext.createOscillator();
    const gainNode = audioContext.createGain();
    
    oscillator.connect(gainNode);
    gainNode.connect(audioContext.destination);
    
    // Different tones for success vs failure
    oscillator.frequency.value = type === 'success' ? 880 : 440; // A5 for success, A4 for failure
    oscillator.type = 'sine';
    
    gainNode.gain.setValueAtTime(0.1, audioContext.currentTime);
    gainNode.gain.exponentialRampToValueAtTime(0.01, audioContext.currentTime + 0.3);
    
    oscillator.start(audioContext.currentTime);
    oscillator.stop(audioContext.currentTime + 0.3);
  } catch (e) {
    // Audio not available
  }
};

// Job type configurations
const JOB_CONFIGS = {
  data_collection: {
    label: 'Data Collection',
    icon: Database,
    color: 'text-blue-400',
    bgColor: 'bg-blue-500/20',
    description: 'Collect historical price data from Interactive Brokers'
  },
  backtest: {
    label: 'Backtest',
    icon: TrendingUp,
    color: 'text-amber-400',
    bgColor: 'bg-amber-500/20',
    description: 'Run strategy simulations on historical data'
  },
  training: {
    label: 'AI Training',
    icon: Activity,
    color: 'text-purple-400',
    bgColor: 'bg-purple-500/20',
    description: 'Train AI prediction models'
  },
  calibration: {
    label: 'Calibration',
    icon: BarChart3,
    color: 'text-cyan-400',
    bgColor: 'bg-cyan-500/20',
    description: 'Calibrate trading parameters'
  }
};

// Collection type options
const COLLECTION_TYPES = [
  { value: 'liquid', label: 'Liquid Stocks', description: 'High volume stocks (fastest)' },
  { value: 'full_market', label: 'Full Market', description: 'All US stocks (slower)' },
  { value: 'smart', label: 'Smart Collection', description: 'Only stocks needing updates' }
];

// Bar size options
const BAR_SIZES = [
  { value: '1 day', label: '1 Day' },
  { value: '1 hour', label: '1 Hour' },
  { value: '30 mins', label: '30 Minutes' },
  { value: '15 mins', label: '15 Minutes' },
  { value: '5 mins', label: '5 Minutes' },
  { value: '1 min', label: '1 Minute' }
];

// Status badge component
const StatusBadge = ({ status }) => {
  const configs = {
    pending: { bg: 'bg-zinc-500/20', text: 'text-zinc-400', icon: Clock },
    running: { bg: 'bg-blue-500/20', text: 'text-blue-400', icon: Loader2 },
    completed: { bg: 'bg-green-500/20', text: 'text-green-400', icon: CheckCircle },
    failed: { bg: 'bg-red-500/20', text: 'text-red-400', icon: XCircle },
    cancelled: { bg: 'bg-amber-500/20', text: 'text-amber-400', icon: XCircle }
  };
  
  const config = configs[status] || configs.pending;
  const Icon = config.icon;
  
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${config.bg} ${config.text}`}>
      <Icon className={`w-3 h-3 ${status === 'running' ? 'animate-spin' : ''}`} />
      {status}
    </span>
  );
};

// Progress bar component
const ProgressBar = ({ percent, message }) => (
  <div className="w-full">
    <div className="flex justify-between text-xs mb-1">
      <span className="text-zinc-400">{message || 'Processing...'}</span>
      <span className="text-zinc-500">{percent}%</span>
    </div>
    <div className="w-full h-1.5 bg-zinc-800 rounded-full overflow-hidden">
      <motion.div 
        className="h-full bg-gradient-to-r from-cyan-500 to-blue-500"
        initial={{ width: 0 }}
        animate={{ width: `${percent}%` }}
        transition={{ duration: 0.3 }}
      />
    </div>
  </div>
);

const JobManager = ({ compact = false }) => {
  const { focusMode, setMode, resetToLive } = useFocusMode();
  
  // UI State
  const [isExpanded, setIsExpanded] = useState(!compact);
  const [activeTab, setActiveTab] = useState('data_collection');
  const [isCreating, setIsCreating] = useState(false);
  
  // Jobs data
  const [jobs, setJobs] = useState([]);
  const [runningJobs, setRunningJobs] = useState([]);
  const [loadingJobs, setLoadingJobs] = useState(false);
  
  // Notification settings
  const [notificationsEnabled, setNotificationsEnabled] = useState(() => {
    const saved = localStorage.getItem('sentcom_job_notifications');
    return saved !== 'false'; // Default to enabled
  });
  const [notificationPermission, setNotificationPermission] = useState('default');
  const previousJobsRef = useRef(new Map()); // Track previous job states
  
  // Data Collection form state
  const [collectionType, setCollectionType] = useState('liquid');
  const [collectionBarSize, setCollectionBarSize] = useState('1 day');
  const [collectionDuration, setCollectionDuration] = useState('1 M');
  const [minAdv, setMinAdv] = useState(100000);
  
  // Backtest form state
  const [backtestStartDate, setBacktestStartDate] = useState(() => {
    const d = new Date();
    d.setFullYear(d.getFullYear() - 1);
    return d.toISOString().split('T')[0];
  });
  const [backtestEndDate, setBacktestEndDate] = useState(() => new Date().toISOString().split('T')[0]);
  const [backtestBarSize, setBacktestBarSize] = useState('1 day');
  const [backtestCapital, setBacktestCapital] = useState(100000);
  const [backtestUniverse, setBacktestUniverse] = useState('all');
  const [useAiAgents, setUseAiAgents] = useState(true);
  
  // Check notification permission on mount
  useEffect(() => {
    if ('Notification' in window) {
      setNotificationPermission(Notification.permission);
    }
  }, []);
  
  // Save notification preference
  useEffect(() => {
    localStorage.setItem('sentcom_job_notifications', notificationsEnabled.toString());
  }, [notificationsEnabled]);
  
  // Toggle notifications
  const toggleNotifications = async () => {
    if (!notificationsEnabled) {
      // Enabling - request permission first
      const granted = await requestNotificationPermission();
      if (granted) {
        setNotificationsEnabled(true);
        setNotificationPermission('granted');
        toast.success('Job notifications enabled!');
      } else {
        toast.error('Please allow notifications in your browser settings');
      }
    } else {
      setNotificationsEnabled(false);
      toast.info('Job notifications disabled');
    }
  };
  
  // Notify on job completion
  const notifyJobComplete = useCallback((job, wasRunning) => {
    if (!notificationsEnabled) return;
    
    const config = JOB_CONFIGS[job.job_type] || JOB_CONFIGS.data_collection;
    const isSuccess = job.status === 'completed';
    
    // Show browser notification
    if (isSuccess) {
      let body = `${config.label} completed successfully!`;
      if (job.job_type === 'backtest' && job.result?.metrics) {
        body = `Return: ${(job.result.metrics.total_return_pct || 0).toFixed(1)}%`;
      } else if (job.job_type === 'data_collection' && job.result?.total_symbols) {
        body = `${job.result.total_symbols} symbols processed`;
      } else if (job.job_type === 'training' && job.result?.accuracy_percent) {
        body = `Accuracy: ${job.result.accuracy_percent}`;
      }
      showBrowserNotification(`✅ ${config.label} Complete`, body);
      playNotificationSound('success');
    } else if (job.status === 'failed') {
      showBrowserNotification(`❌ ${config.label} Failed`, job.error || 'Job failed');
      playNotificationSound('failure');
    }
    
    // Also show in-app toast
    if (isSuccess) {
      toast.success(`${config.label} completed!`, {
        description: job.result?.message || 'Job finished successfully'
      });
    } else if (job.status === 'failed') {
      toast.error(`${config.label} failed`, {
        description: job.error || 'Unknown error'
      });
    }
  }, [notificationsEnabled]);
  
  // Load jobs and check for completions
  const loadJobs = useCallback(async () => {
    setLoadingJobs(true);
    try {
      const [recentRes, runningRes] = await Promise.all([
        api.get('/api/jobs', { params: { limit: 10 } }),
        api.get('/api/jobs/running')
      ]);
      
      const newJobs = recentRes.data.jobs || [];
      const newRunningJobs = runningRes.data.running_jobs || [];
      
      // Check for job completions (job was running, now completed/failed)
      newJobs.forEach(job => {
        const previousStatus = previousJobsRef.current.get(job.job_id);
        if (previousStatus === 'running' && (job.status === 'completed' || job.status === 'failed')) {
          notifyJobComplete(job, true);
        }
      });
      
      // Update previous jobs map
      previousJobsRef.current.clear();
      newJobs.forEach(job => {
        previousJobsRef.current.set(job.job_id, job.status);
      });
      
      setJobs(newJobs);
      setRunningJobs(newRunningJobs);
    } catch (err) {
      console.error('Failed to load jobs:', err);
    } finally {
      setLoadingJobs(false);
    }
  }, [notifyJobComplete]);
  
  // Initial load and polling
  useEffect(() => {
    loadJobs();
    return safePolling(loadJobs, 5000, { immediate: false });
  }, [loadJobs]);
  
  // Create data collection job
  const handleCreateCollectionJob = async () => {
    setIsCreating(true);
    try {
      const response = await api.post('/api/jobs', {
        job_type: 'data_collection',
        params: {
          collection_type: collectionType,
          bar_size: collectionBarSize,
          duration: collectionDuration,
          min_adv: minAdv
        },
        auto_start: true
      });
      
      if (response.data.success) {
        toast.success(`Data collection job created!`);
        loadJobs();
      } else {
        throw new Error(response.data.error);
      }
    } catch (err) {
      toast.error(`Failed to create job: ${err.message}`);
    } finally {
      setIsCreating(false);
    }
  };
  
  // Create backtest job
  const handleCreateBacktestJob = async () => {
    setIsCreating(true);
    try {
      const response = await api.post('/api/jobs', {
        job_type: 'backtest',
        params: {
          start_date: `${backtestStartDate}T00:00:00Z`,
          end_date: `${backtestEndDate}T23:59:59Z`,
          bar_size: backtestBarSize,
          starting_capital: backtestCapital,
          universe: backtestUniverse,
          use_ai_agents: useAiAgents
        },
        auto_start: true
      });
      
      if (response.data.success) {
        toast.success(`Backtest job created!`);
        loadJobs();
      } else {
        throw new Error(response.data.error);
      }
    } catch (err) {
      toast.error(`Failed to create job: ${err.message}`);
    } finally {
      setIsCreating(false);
    }
  };
  
  // Cancel a job
  const handleCancelJob = async (jobId) => {
    try {
      await api.delete(`/api/jobs/${jobId}`);
      toast.success('Job cancelled');
      loadJobs();
    } catch (err) {
      toast.error(`Failed to cancel job: ${err.message}`);
    }
  };
  
  // Format date
  const formatDate = (dateStr) => {
    if (!dateStr) return 'N/A';
    return new Date(dateStr).toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  };
  
  // Render job card
  const renderJobCard = (job) => {
    const config = JOB_CONFIGS[job.job_type] || JOB_CONFIGS.data_collection;
    const Icon = config.icon;
    const progress = job.progress || {};
    
    return (
      <motion.div
        key={job.job_id}
        layout
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, height: 0 }}
        className="glass-panel p-3 mb-2"
      >
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-2">
            <div className={`p-1.5 rounded ${config.bgColor}`}>
              <Icon className={`w-4 h-4 ${config.color}`} />
            </div>
            <div>
              <div className="text-sm font-medium text-white flex items-center gap-2">
                {config.label}
                <StatusBadge status={job.status} />
              </div>
              <div className="text-xs text-zinc-500">
                {formatDate(job.created_at)}
              </div>
            </div>
          </div>
          
          {(job.status === 'pending' || job.status === 'running') && (
            <button
              onClick={() => handleCancelJob(job.job_id)}
              className="p-1 hover:bg-red-500/20 rounded transition-colors"
              title="Cancel job"
            >
              <X className="w-4 h-4 text-red-400" />
            </button>
          )}
        </div>
        
        {/* Progress for running jobs */}
        {job.status === 'running' && progress.percent !== undefined && (
          <div className="mt-3">
            <ProgressBar percent={progress.percent} message={progress.message} />
          </div>
        )}
        
        {/* Result summary for completed jobs */}
        {job.status === 'completed' && job.result && (
          <div className="mt-2 text-xs text-green-400">
            {job.job_type === 'backtest' && job.result.metrics && (
              <span>Return: {(job.result.metrics.total_return_pct || 0).toFixed(1)}%</span>
            )}
            {job.job_type === 'data_collection' && (
              <span>{job.result.total_symbols || 0} symbols processed</span>
            )}
          </div>
        )}
        
        {/* Error for failed jobs */}
        {job.status === 'failed' && job.error && (
          <div className="mt-2 text-xs text-red-400 truncate">
            {job.error}
          </div>
        )}
      </motion.div>
    );
  };

  return (
    <div className="glass-panel" data-testid="job-manager">
      {/* Header */}
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full flex items-center justify-between p-4"
        data-testid="job-manager-toggle"
      >
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-gradient-to-br from-blue-500/20 to-cyan-500/20">
            <Activity className="w-5 h-5 text-cyan-400" />
          </div>
          <div className="text-left">
            <h3 className="text-lg font-bold text-white">Background Jobs</h3>
            <p className="text-xs text-zinc-400">
              {runningJobs.length > 0 
                ? `${runningJobs.length} job${runningJobs.length > 1 ? 's' : ''} running`
                : 'Data collection & backtesting'
              }
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {/* Notification toggle */}
          <button
            onClick={(e) => {
              e.stopPropagation();
              toggleNotifications();
            }}
            className={`p-1.5 rounded-lg transition-colors ${
              notificationsEnabled 
                ? 'bg-green-500/20 text-green-400 hover:bg-green-500/30' 
                : 'bg-zinc-700/50 text-zinc-500 hover:bg-zinc-600/50'
            }`}
            title={notificationsEnabled ? 'Notifications enabled' : 'Notifications disabled'}
            data-testid="job-notifications-toggle"
          >
            {notificationsEnabled ? (
              <Bell className="w-4 h-4" />
            ) : (
              <BellOff className="w-4 h-4" />
            )}
          </button>
          {runningJobs.length > 0 && (
            <div className="flex items-center gap-1 px-2 py-1 rounded-full bg-blue-500/20">
              <Loader2 className="w-3 h-3 text-blue-400 animate-spin" />
              <span className="text-xs text-blue-400">{runningJobs.length}</span>
            </div>
          )}
          {isExpanded ? (
            <ChevronUp className="w-5 h-5 text-zinc-400" />
          ) : (
            <ChevronDown className="w-5 h-5 text-zinc-400" />
          )}
        </div>
      </button>
      
      <AnimatePresence>
        {isExpanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden"
          >
            <div className="px-4 pb-4">
              {/* Tab buttons - only show Data Collection and Backtest forms */}
              <div className="flex gap-2 mb-4">
                {['data_collection', 'backtest'].map((key) => {
                  const config = JOB_CONFIGS[key];
                  const Icon = config.icon;
                  return (
                    <button
                      key={key}
                      onClick={() => setActiveTab(key)}
                      className={`flex-1 flex items-center justify-center gap-2 py-2 px-3 rounded-lg text-sm font-medium transition-colors ${
                        activeTab === key
                          ? `${config.bgColor} ${config.color} border border-current/30`
                          : 'bg-zinc-800/50 text-zinc-400 hover:bg-zinc-700/50'
                      }`}
                      data-testid={`job-tab-${key}`}
                    >
                      <Icon className="w-4 h-4" />
                      {config.label}
                    </button>
                  );
                })}
              </div>
              
              {/* Data Collection Form */}
              {activeTab === 'data_collection' && (
                <div className="space-y-4">
                  {/* Collection Type */}
                  <div>
                    <label className="text-xs text-zinc-400 block mb-1">Collection Type</label>
                    <div className="grid grid-cols-3 gap-2">
                      {COLLECTION_TYPES.map(type => (
                        <button
                          key={type.value}
                          onClick={() => setCollectionType(type.value)}
                          className={`p-2 rounded-lg text-left transition-colors ${
                            collectionType === type.value
                              ? 'bg-blue-500/20 border border-blue-500/30'
                              : 'bg-zinc-800/50 hover:bg-zinc-700/50'
                          }`}
                        >
                          <div className={`text-sm font-medium ${collectionType === type.value ? 'text-blue-400' : 'text-white'}`}>
                            {type.label}
                          </div>
                          <div className="text-xs text-zinc-500">{type.description}</div>
                        </button>
                      ))}
                    </div>
                  </div>
                  
                  {/* Bar Size & Duration */}
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <label className="text-xs text-zinc-400 block mb-1">Bar Size</label>
                      <select
                        value={collectionBarSize}
                        onChange={(e) => setCollectionBarSize(e.target.value)}
                        className="w-full bg-zinc-800 text-white rounded-lg px-3 py-2 text-sm border border-zinc-700"
                      >
                        {BAR_SIZES.map(bs => (
                          <option key={bs.value} value={bs.value}>{bs.label}</option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <label className="text-xs text-zinc-400 block mb-1">Min ADV</label>
                      <input
                        type="number"
                        value={minAdv}
                        onChange={(e) => setMinAdv(parseInt(e.target.value) || 100000)}
                        className="w-full bg-zinc-800 text-white rounded-lg px-3 py-2 text-sm border border-zinc-700"
                        min={0}
                        step={10000}
                      />
                    </div>
                  </div>
                  
                  {/* Start Button */}
                  <button
                    onClick={handleCreateCollectionJob}
                    disabled={isCreating || focusMode !== 'live'}
                    className="w-full py-3 rounded-lg bg-gradient-to-r from-blue-500 to-cyan-500 text-white font-medium flex items-center justify-center gap-2 hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed"
                    data-testid="start-collection-btn"
                  >
                    {isCreating ? (
                      <>
                        <Loader2 className="w-4 h-4 animate-spin" />
                        Creating...
                      </>
                    ) : (
                      <>
                        <Play className="w-4 h-4" />
                        Start Data Collection
                      </>
                    )}
                  </button>
                  
                  {focusMode !== 'live' && (
                    <div className="text-xs text-amber-400 text-center">
                      Another task is running. Wait for it to complete or cancel it.
                    </div>
                  )}
                </div>
              )}
              
              {/* Backtest Form */}
              {activeTab === 'backtest' && (
                <div className="space-y-4">
                  {/* Date Range */}
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <label className="text-xs text-zinc-400 block mb-1">Start Date</label>
                      <input
                        type="date"
                        value={backtestStartDate}
                        onChange={(e) => setBacktestStartDate(e.target.value)}
                        className="w-full bg-zinc-800 text-white rounded-lg px-3 py-2 text-sm border border-zinc-700"
                      />
                    </div>
                    <div>
                      <label className="text-xs text-zinc-400 block mb-1">End Date</label>
                      <input
                        type="date"
                        value={backtestEndDate}
                        onChange={(e) => setBacktestEndDate(e.target.value)}
                        className="w-full bg-zinc-800 text-white rounded-lg px-3 py-2 text-sm border border-zinc-700"
                      />
                    </div>
                  </div>
                  
                  {/* Capital & Bar Size */}
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <label className="text-xs text-zinc-400 block mb-1">Starting Capital</label>
                      <input
                        type="number"
                        value={backtestCapital}
                        onChange={(e) => setBacktestCapital(parseInt(e.target.value) || 100000)}
                        className="w-full bg-zinc-800 text-white rounded-lg px-3 py-2 text-sm border border-zinc-700"
                        min={1000}
                        step={1000}
                      />
                    </div>
                    <div>
                      <label className="text-xs text-zinc-400 block mb-1">Bar Size</label>
                      <select
                        value={backtestBarSize}
                        onChange={(e) => setBacktestBarSize(e.target.value)}
                        className="w-full bg-zinc-800 text-white rounded-lg px-3 py-2 text-sm border border-zinc-700"
                      >
                        {BAR_SIZES.map(bs => (
                          <option key={bs.value} value={bs.value}>{bs.label}</option>
                        ))}
                      </select>
                    </div>
                  </div>
                  
                  {/* AI Agents Toggle */}
                  <div className="flex items-center justify-between p-3 bg-zinc-800/50 rounded-lg">
                    <div>
                      <div className="text-sm text-white">Use AI Agents</div>
                      <div className="text-xs text-zinc-500">Run full AI consultation pipeline</div>
                    </div>
                    <button
                      onClick={() => setUseAiAgents(!useAiAgents)}
                      className={`w-10 h-5 rounded-full transition-colors ${
                        useAiAgents ? 'bg-purple-500' : 'bg-zinc-600'
                      }`}
                    >
                      <div className={`w-4 h-4 bg-white rounded-full transition-transform ${
                        useAiAgents ? 'translate-x-5' : 'translate-x-0.5'
                      }`} />
                    </button>
                  </div>
                  
                  {/* Start Button */}
                  <button
                    onClick={handleCreateBacktestJob}
                    disabled={isCreating || focusMode !== 'live'}
                    className="w-full py-3 rounded-lg bg-gradient-to-r from-amber-500 to-orange-500 text-white font-medium flex items-center justify-center gap-2 hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed"
                    data-testid="start-backtest-btn"
                  >
                    {isCreating ? (
                      <>
                        <Loader2 className="w-4 h-4 animate-spin" />
                        Creating...
                      </>
                    ) : (
                      <>
                        <BarChart3 className="w-4 h-4" />
                        Start Backtest
                      </>
                    )}
                  </button>
                </div>
              )}
              
              {/* Recent Jobs */}
              <div className="mt-6">
                <div className="flex items-center justify-between mb-3">
                  <h4 className="text-sm font-medium text-zinc-300">Recent Jobs</h4>
                  <button
                    onClick={loadJobs}
                    disabled={loadingJobs}
                    className="p-1 hover:bg-zinc-700 rounded transition-colors"
                    title="Refresh"
                  >
                    <RefreshCw className={`w-4 h-4 text-zinc-400 ${loadingJobs ? 'animate-spin' : ''}`} />
                  </button>
                </div>
                
                <div className="max-h-64 overflow-y-auto">
                  <AnimatePresence>
                    {jobs.length === 0 ? (
                      <div className="text-center py-6 text-zinc-500 text-sm">
                        No recent jobs
                      </div>
                    ) : (
                      jobs.map(renderJobCard)
                    )}
                  </AnimatePresence>
                </div>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};

export default JobManager;
