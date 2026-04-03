/* ── GTM Planning Engine - API Client ── */

(function() {
  'use strict';

  /**
   * Debug logging utility
   * Set DEBUG_MODE to false in production to disable all logging
   */
  const DEBUG_MODE = true;

  /**
   * Debug logging function
   * @param {string} module - Module name for the log
   * @param {string} message - Log message
   * @param {any} data - Optional data to log
   */
  function debug_log(module, message, data = null) {
    if (DEBUG_MODE) {
      const timestamp = new Date().toISOString().split('T')[1].split('.')[0];
      const log_message = `[${timestamp}] ${module} - ${message}`;
      if (data !== null) {
        console.log(log_message, data);
      } else {
        console.log(log_message);
      }
    }
  }

  /**
   * Error logging function (always logs)
   * @param {string} module - Module name for the error
   * @param {string} message - Error message
   * @param {Error} error - Error object
   */
  function error_log(module, message, error = null) {
    const timestamp = new Date().toISOString().split('T')[1].split('.')[0];
    const log_message = `[${timestamp}] ${module} - ${message}`;
    if (error !== null) {
      console.error(log_message, error);
    } else {
      console.error(log_message);
    }
  }

  /**
   * API Client configuration
   */
  const API_CONFIG = {
    base_url: '/api',
    default_headers: {
      'Content-Type': 'application/json',
      'Accept': 'application/json'
    }
  };

  /**
   * API Client state
   */
  const API_STATE = {};

  /**
   * Build full URL for API endpoint
   * @param {string} endpoint - The API endpoint path
   * @returns {string} Full URL
   */
  function build_url(endpoint) {
    // Remove leading slash if present
    const clean_endpoint = endpoint.startsWith('/') ? endpoint.slice(1) : endpoint;
    return `${API_CONFIG.base_url}/${clean_endpoint}`;
  }

  /**
   * Make an HTTP request with logging
   * @param {string} method - HTTP method (GET, POST, PUT, DELETE, etc.)
   * @param {string} endpoint - API endpoint
   * @param {object} options - Request options (body, headers, etc.)
   * @returns {Promise} Promise that resolves with response data
   */
  async function request(method, endpoint, options = {}) {
    const url = build_url(endpoint);

    // Prepare headers
    const headers = {
      ...API_CONFIG.default_headers,
      ...options.headers
    };

    // Prepare request config
    const config = {
      method: method.toUpperCase(),
      headers: headers,
      ...options
    };

    // Add body for non-GET requests
    if (method.toUpperCase() !== 'GET' && options.body) {
      if (typeof options.body === 'object') {
        config.body = JSON.stringify(options.body);
      } else {
        config.body = options.body;
      }
    }

    debug_log('API Client', `${method.toUpperCase()} ${endpoint}`, options.body);

    try {
      const response = await fetch(url, config);

      // Handle non-OK responses
      if (!response.ok) {
        const error_data = await response.json().catch(() => ({
          error: 'Unknown error'
        }));
        error_log('API Client', `HTTP ${response.status} for ${method.toUpperCase()} ${endpoint}`);
        throw new APIError(error_data.error || `HTTP ${response.status}`, response.status, error_data);
      }

      // Parse JSON response
      const data = await response.json();
      debug_log('API Client', `Response from ${method.toUpperCase()} ${endpoint}`, data);
      return data;

    } catch (error) {
      // Re-throw API errors
      if (error instanceof APIError) {
        throw error;
      }

      // Handle network errors
      error_log('API Client', `Network error for ${method.toUpperCase()} ${endpoint}`, error);
      throw new APIError(error.message || 'Network error', 0, null);
    }
  }

  /**
   * Custom Error class for API errors
   */
  class APIError extends Error {
    constructor(message, status, data) {
      super(message);
      this.name = 'APIError';
      this.status = status;
      this.data = data;
    }
  }

  /**
   * API Methods
   */
  const API = {
    /**
     * GET request
     * @param {string} endpoint - API endpoint
     * @param {object} options - Request options
     * @returns {Promise} Promise that resolves with response data
     */
    get: function(endpoint, options = {}) {
      return request('GET', endpoint, options);
    },

    /**
     * POST request
     * @param {string} endpoint - API endpoint
     * @param {object} body - Request body
     * @param {object} options - Request options
     * @returns {Promise} Promise that resolves with response data
     */
    post: function(endpoint, body, options = {}) {
      return request('POST', endpoint, { ...options, body });
    },

    /**
     * PUT request
     * @param {string} endpoint - API endpoint
     * @param {object} body - Request body
     * @param {object} options - Request options
     * @returns {Promise} Promise that resolves with response data
     */
    put: function(endpoint, body, options = {}) {
      return request('PUT', endpoint, { ...options, body });
    },

    /**
     * DELETE request
     * @param {string} endpoint - API endpoint
     * @param {object} options - Request options
     * @returns {Promise} Promise that resolves with response data
     */
    delete: function(endpoint, options = {}) {
      return request('DELETE', endpoint, options);
    }
  };



  /**
   * Public API for API Client
   */
  window.APIClient = {
    config: API_CONFIG,
    state: API_STATE,
    request: request,
    error: APIError,
    api: API
  };

})();
