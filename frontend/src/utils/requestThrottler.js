/**
 * Request Throttler - Limits concurrent API requests
 * 
 * Prevents ERR_INSUFFICIENT_RESOURCES by queuing requests
 * and only allowing a limited number to run at once.
 * 
 * Browser limits: 6 concurrent connections per domain.
 * Reserve slots for: 2 WebSockets + 2 user actions = 4 reserved.
 * Throttler gets: 2 concurrent slots for background polling.
 */

class RequestThrottler {
  constructor(maxConcurrent = 2) {
    this.maxConcurrent = maxConcurrent;
    this.activeRequests = 0;
    this.queue = [];
    this.enabled = true;
    this.paused = false;
  }

  async throttle(requestFn) {
    if (!this.enabled || this.paused) {
      // When paused, drop polling requests silently
      if (this.paused) {
        return Promise.resolve({ data: null });
      }
      return requestFn();
    }

    return new Promise((resolve, reject) => {
      const execute = async () => {
        this.activeRequests++;
        try {
          const result = await requestFn();
          resolve(result);
        } catch (error) {
          reject(error);
        } finally {
          this.activeRequests--;
          if (!this.paused) {
            this.processQueue();
          }
        }
      };

      if (this.activeRequests < this.maxConcurrent) {
        execute();
      } else {
        this.queue.push(execute);
      }
    });
  }

  processQueue() {
    while (this.queue.length > 0 && this.activeRequests < this.maxConcurrent && !this.paused) {
      const next = this.queue.shift();
      next();
    }
  }

  getStatus() {
    return {
      active: this.activeRequests,
      queued: this.queue.length,
      max: this.maxConcurrent,
      paused: this.paused
    };
  }

  // Pause polling and flush queue — frees connection slots for user actions
  pause(durationMs = 5000) {
    this.paused = true;
    const dropped = this.queue.length;
    this.queue = [];
    if (dropped > 0) {
      console.log(`[Throttler] Paused: dropped ${dropped} queued requests`);
    }
    // Auto-resume after duration
    setTimeout(() => this.resume(), durationMs);
    return dropped;
  }

  resume() {
    this.paused = false;
    this.processQueue();
  }

  clearQueue() {
    const dropped = this.queue.length;
    this.queue = [];
    return dropped;
  }

  setMaxConcurrent(max) {
    this.maxConcurrent = max;
    this.processQueue();
  }

  enable() { this.enabled = true; }
  disable() { this.enabled = false; }
}

// Browser: 6 connections. Reserve 2 for WebSockets + 2 for user POSTs = 2 for polling.
export const requestThrottler = new RequestThrottler(2);

export default RequestThrottler;
