import { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';
import api, { safeGet } from '../../../utils/api';
import { safePolling } from '../../../utils/safePolling';

// Hook for AI Modules status and control
export const useAIModules = (pollInterval = 60000) => {
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(null);

  const fetchStatus = useCallback(async () => {
    try {
      const data = await safeGet('/api/ai-modules/status');
      if (data && data.success) {
        setStatus(data.status);
      }
    } catch (err) {
      // Silent — non-critical service
    } finally {
      setLoading(false);
    }
  }, []);

  const toggleModule = useCallback(async (moduleName, enabled) => {
    setActionLoading(moduleName);
    try {
      const { data } = await api.post(`/api/ai-modules/toggle/${moduleName}`, { enabled });
      if (data?.success) {
        await fetchStatus();
        toast.success(`${moduleName.replace('_', ' ')} ${enabled ? 'enabled' : 'disabled'}`);
      }
    } catch (err) {
      console.error('Error toggling module:', err);
      toast.error('Failed to toggle module');
    } finally {
      setActionLoading(null);
    }
  }, [fetchStatus]);

  const setGlobalShadowMode = useCallback(async (shadowMode) => {
    setActionLoading('shadow');
    try {
      const { data } = await api.post('/api/ai-modules/shadow-mode', { shadow_mode: shadowMode });
      if (data?.success) {
        await fetchStatus();
        toast.success(`Shadow mode ${shadowMode ? 'enabled' : 'disabled'}`);
      }
    } catch (err) {
      console.error('Error setting shadow mode:', err);
      toast.error('Failed to set shadow mode');
    } finally {
      setActionLoading(null);
    }
  }, [fetchStatus]);

  useEffect(() => {
    // Delay initial fetch to reduce startup burst — AI module status changes rarely
    const timer = setTimeout(() => fetchStatus(), 10000);
    const cleanup = safePolling(fetchStatus, pollInterval, { immediate: false });
    return () => { clearTimeout(timer); cleanup(); };
  }, [fetchStatus, pollInterval]);

  return { status, loading, actionLoading, toggleModule, setGlobalShadowMode, refresh: fetchStatus };
};
