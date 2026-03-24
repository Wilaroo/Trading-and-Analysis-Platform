/**
 * Request Throttler - Limits concurrent API requests
 * 
 * Prevents ERR_INSUFFICIENT_RESOURCES by queuing requests
 * and only allowing a limited number to run at once.
 */

class RequestThrottler {
  constructor(maxConcurrent = 4) {
    this.maxConcurrent = maxConcurrent;
    this.activeRequests = 0;
    this.queue = [];
    this.enabled = true;
  }

  async throttle(requestFn) {
    if (!this.enabled) {
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
          this.processQueue();
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
    while (this.queue.length > 0 && this.activeRequests < this.maxConcurrent) {
      const next = this.queue.shift();
      next();
    }
  }

  getStatus() {
    return {
      active: this.activeRequests,
      queued: this.queue.length,
      max: this.maxConcurrent
    };
  }

  // Clear all queued (not yet started) requests to prevent stale buildup
  clearQueue() {
    const dropped = this.queue.length;
    this.queue = [];
    return dropped;
  }

  setMaxConcurrent(max) {
    this.maxConcurrent = max;
    this.processQueue();
  }

  enable() {
    this.enabled = true;
  }

  disable() {
    this.enabled = false;
  }
}

// Global throttler instance - limit to 16 concurrent requests
export const requestThrottler = new RequestThrottler(16);

export default RequestThrottler;
