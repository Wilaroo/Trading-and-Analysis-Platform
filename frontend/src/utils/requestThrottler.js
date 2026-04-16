/**
 * Request Throttler — Limits concurrent background polling requests.
 *
 * Browser allows 6 connections per domain. We reserve 2 for WebSockets
 * and 2 for user-initiated POST/PUT/DELETE, leaving 2 for background GET polls.
 *
 * Features:
 * - Configurable concurrency limit
 * - Queue drain (cancel all pending GETs)
 * - Pause/resume (reject new requests while paused)
 * - AbortController support for cancelling in-flight requests
 */

class RequestThrottler {
  constructor(maxConcurrent = 4) {
    this.maxConcurrent = maxConcurrent;
    this.activeRequests = 0;
    this.queue = [];
    this._paused = false;
  }

  /**
   * Throttle a request function. Queued if at capacity.
   * Returns a rejected promise if paused (non-essential polls should fail silently).
   */
  async throttle(requestFn) {
    // While paused, immediately reject — callers (safeGet etc.) swallow errors
    if (this._paused) {
      return Promise.reject(new Error('Throttler paused for training'));
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
        this.queue.push({ execute, reject });
      }
    });
  }

  processQueue() {
    if (this._paused) return;
    while (this.queue.length > 0 && this.activeRequests < this.maxConcurrent) {
      const next = this.queue.shift();
      next.execute();
    }
  }

  /**
   * Drain all queued (not yet started) requests.
   * Active in-flight requests will complete naturally.
   */
  drainQueue() {
    const drained = this.queue.length;
    this.queue.forEach(item => {
      item.reject(new Error('Request cancelled — queue drained'));
    });
    this.queue = [];
    return drained;
  }

  /**
   * Pause the throttler — drains the queue and rejects new requests.
   * Call before user-critical actions (e.g., starting training) to free browser connections.
   */
  pause() {
    this._paused = true;
    this.drainQueue();
  }

  /**
   * Resume normal throttling.
   */
  resume() {
    this._paused = false;
  }

  get paused() {
    return this._paused;
  }

  getStatus() {
    return {
      active: this.activeRequests,
      queued: this.queue.length,
      max: this.maxConcurrent,
      paused: this._paused
    };
  }
}

// 1 concurrent slot for background polling
// Browser limit 6 — 2 WebSockets — 3 reserved for user actions = 1 for background GETs
export const requestThrottler = new RequestThrottler(1);

export default RequestThrottler;
