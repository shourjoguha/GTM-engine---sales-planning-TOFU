/* ── GTM Planning Engine - Logger Utility ── */

(function() {
  'use strict';

  const LOG_LEVELS = {
    DEBUG: 0,
    INFO: 1,
    WARN: 2,
    ERROR: 3
  };

  let current_log_level = LOG_LEVELS.DEBUG;

  function log(level, module, message) {
    if (level >= current_log_level) {
      const timestamp = new Date().toISOString().slice(0, 19);
      const level_name = Object.keys(LOG_LEVELS)[level];
      console.log(`[${timestamp}] [${level_name}] [${module}] ${message}`);
    }
  }

  window.Logger = {
    setLevel: (level) => { current_log_level = level; },
    debug: (module, message) => log(LOG_LEVELS.DEBUG, module, message),
    info: (module, message) => log(LOG_LEVELS.INFO, module, message),
    warn: (module, message) => log(LOG_LEVELS.WARN, module, message),
    error: (module, message) => log(LOG_LEVELS.ERROR, module, message)
  };
})();
