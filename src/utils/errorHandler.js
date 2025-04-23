import loggingService from '../services/LoggingService';

// Global error handler for unhandled exceptions
export const setupGlobalErrorHandler = () => {
  window.addEventListener('error', (event) => {
    loggingService.logError('Unhandled error', event.error);
  });

  window.addEventListener('unhandledrejection', (event) => {
    loggingService.logError('Unhandled promise rejection', event.reason);
  });
};

// Wrapper for API calls to catch and log errors
export const withErrorLogging = async (apiCall, context = '') => {
  try {
    return await apiCall();
  } catch (error) {
    loggingService.logError(`API error${context ? ` in ${context}` : ''}`, error);
    throw error; // Re-throw for component handling
  }
};
