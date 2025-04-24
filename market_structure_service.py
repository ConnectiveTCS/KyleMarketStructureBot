import sys
import os
import time
import socket
import servicemanager
import win32event
import win32service
import win32serviceutil
import logging

# Configure logging for the service
logging.basicConfig(
    filename='c:\\Coding\\Market Structure Shift\\service_log.txt',
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('MarketStructureService')

class MarketStructureService(win32serviceutil.ServiceFramework):
    _svc_name_ = "MarketStructureBot"
    _svc_display_name_ = "Market Structure Bot Service"
    _svc_description_ = "Runs the Market Structure Bot Flask application"

    def __init__(self, args):
        win32serviceutil.ServiceFramework.__init__(self, args)
        self.stop_event = win32event.CreateEvent(None, 0, 0, None)
        self.is_running = False
        socket.setdefaulttimeout(60)

    def SvcStop(self):
        logger.info('Service stop requested')
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        win32event.SetEvent(self.stop_event)
        self.is_running = False

    def SvcDoRun(self):
        logger.info('Service is starting')
        self.ReportServiceStatus(win32service.SERVICE_RUNNING)
        self.is_running = True
        self.main()

    def main(self):
        logger.info('Starting Market Structure Bot application')
        
        # Set working directory to where app.py is located
        app_dir = os.path.dirname(os.path.abspath(__file__))
        os.chdir(app_dir)
        
        # Add the app directory to the Python path
        if app_dir not in sys.path:
            sys.path.append(app_dir)
            
        # Use a subprocess to run the application
        import subprocess
        process = None
        
        try:
            # Start the Flask app in a subprocess
            # Use 0.0.0.0 to listen on all interfaces
            process = subprocess.Popen([
                sys.executable,
                os.path.join(app_dir, 'app.py')
            ], 
            cwd=app_dir,
            env=dict(os.environ, FLASK_APP='app.py', FLASK_RUN_HOST='0.0.0.0', FLASK_RUN_PORT='5000'))
            
            logger.info(f'Application process started with PID: {process.pid}')
            
            # Check the process every 5 seconds
            while self.is_running:
                # Check if stop event is triggered
                rc = win32event.WaitForSingleObject(self.stop_event, 5000)
                
                # If service stop is requested or the process has terminated
                if rc == win32event.WAIT_OBJECT_0 or process.poll() is not None:
                    if process.poll() is not None:
                        logger.error('Application process terminated unexpectedly')
                    break
                    
        except Exception as e:
            logger.error(f'Error running the application: {str(e)}')
            
        finally:
            # Clean up
            if process and process.poll() is None:
                logger.info('Terminating application process')
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
            
            logger.info('Service stopped')

if __name__ == '__main__':
    if len(sys.argv) == 1:
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(MarketStructureService)
        servicemanager.StartServiceCtrlDispatcher()
    else:
        win32serviceutil.HandleCommandLine(MarketStructureService)
