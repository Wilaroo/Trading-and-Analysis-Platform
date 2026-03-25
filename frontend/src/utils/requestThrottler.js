/**
 * Request Throttler — Limits concurrent background polling requests.
 *
 * Browser allows 6 connections per domain. We reserve 2 for WebSockets,
 * leaving 4 for HTTP. This throttler ensures background GET polls don't
 * starve user-initiated actions (POST/PUT/DELETE are never throttled).
 */

class RequestThrottler {
  constructor(maxConcurrent = 4) {
    this.maxConcurrent = maxConcurrent;
    this.activeRequests = 0;
    this.queue = [];
  }

  async throttle(requestFn) {
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
}

// 4 concurrent slots for background polling (browser limit 6 minus 2 WebSockets)
export const requestThrottler = new RequestThrottler(4);

export default RequestThrottler;
