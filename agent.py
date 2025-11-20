#!/usr/bin/env python3
"""
GPU Telemetry Agent using NVIDIA DCGM
Collects GPU metrics every 5 seconds and exposes them via Prometheus endpoint
"""

import time
import socket
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread
import pydcgm
import dcgm_structs
import dcgm_agent
import dcgm_fields

class MetricsCollector:
    def __init__(self):
        self.hostname = socket.gethostname()
        self.metrics = {}
        self.dcgm_handle = None
        self.group_id = None
        
    def initialize_dcgm(self):
        """Initialize DCGM and create GPU group"""
        pydcgm.Init()
        self.dcgm_handle = pydcgm.DcgmHandle(ipAddress='127.0.0.1')
        self.dcgm_handle.ConnectToDCGM()
        
        # Create a group with all GPUs
        self.group_id = pydcgm.DcgmGroup(
            self.dcgm_handle,
            groupName='telemetry_group',
            groupType=dcgm_structs.DCGM_GROUP_DEFAULT
        )
        
    def get_gpu_devices(self):
        """Get list of GPU devices"""
        system = pydcgm.DcgmSystem(self.dcgm_handle)
        return system.discovery.GetAllGpuIds()
    
    def collect_metrics(self):
        """Collect all GPU metrics from DCGM"""
        try:
            gpu_ids = self.get_gpu_devices()
            collected = {}
            
            for gpu_id in gpu_ids:
                gpu_metrics = self._collect_gpu_metrics(gpu_id)
                collected[gpu_id] = gpu_metrics
            
            self.metrics = collected
            
        except Exception as e:
            print(f"Error collecting metrics: {e}")
    
    def _collect_gpu_metrics(self, gpu_id):
        """Collect metrics for a single GPU"""
        metrics = {}
        
        # Field IDs to collect
        fields = [
            # Identity
            dcgm_fields.DCGM_FI_DEV_NAME,
            dcgm_fields.DCGM_FI_DEV_BRAND,
            dcgm_fields.DCGM_FI_DEV_SERIAL,
            dcgm_fields.DCGM_FI_DEV_UUID,
            dcgm_fields.DCGM_FI_DEV_FB_TOTAL,
            
            # Health
            dcgm_fields.DCGM_FI_DEV_ECC_SBE_VOL_TOTAL,
            dcgm_fields.DCGM_FI_DEV_ECC_DBE_VOL_TOTAL,
            dcgm_fields.DCGM_FI_DEV_ECC_SBE_AGG_TOTAL,
            dcgm_fields.DCGM_FI_DEV_ECC_DBE_AGG_TOTAL,
            dcgm_fields.DCGM_FI_DEV_RETIRED_SBE,
            dcgm_fields.DCGM_FI_DEV_RETIRED_DBE,
            dcgm_fields.DCGM_FI_DEV_XID_ERRORS,
            dcgm_fields.DCGM_FI_DEV_PCIE_REPLAY_COUNTER,
            
            # Thermal & Power
            dcgm_fields.DCGM_FI_DEV_GPU_TEMP,
            dcgm_fields.DCGM_FI_DEV_POWER_USAGE,
            dcgm_fields.DCGM_FI_DEV_POWER_MGMT_LIMIT,
            dcgm_fields.DCGM_FI_DEV_FAN_SPEED,
            
            # Utilization
            dcgm_fields.DCGM_FI_DEV_GPU_UTIL,
            dcgm_fields.DCGM_FI_DEV_MEM_COPY_UTIL,
            dcgm_fields.DCGM_FI_DEV_FB_USED,
            dcgm_fields.DCGM_FI_DEV_FB_FREE,
            
            # Clocks
            dcgm_fields.DCGM_FI_DEV_SM_CLOCK,
            dcgm_fields.DCGM_FI_DEV_MEM_CLOCK,
            dcgm_fields.DCGM_FI_DEV_SM_CLOCK_MAX,
            dcgm_fields.DCGM_FI_DEV_MEM_CLOCK_MAX,
            
            # Throttle reasons
            dcgm_fields.DCGM_FI_DEV_CLOCK_THROTTLE_REASONS,
        ]
        
        for field_id in fields:
            try:
                value = dcgm_agent.dcgmGetLatestValuesForFields(
                    self.dcgm_handle.handle,
                    gpu_id,
                    [field_id]
                )
                metrics[field_id] = value
            except Exception as e:
                print(f"Error collecting field {field_id} for GPU {gpu_id}: {e}")
        
        return metrics
    
    def get_system_info(self):
        """Get system-level information"""
        try:
            # Get driver version
            driver_version = dcgm_agent.dcgmGetHostDriverVersion(self.dcgm_handle.handle)
            
            # Get DCGM version
            version = dcgm_agent.dcgmVersionInfo()
            dcgm_version = f"{version.major}.{version.minor}.{version.patch}"
            
            return {
                'driver_version': driver_version,
                'dcgm_version': dcgm_version
            }
        except Exception as e:
            print(f"Error getting system info: {e}")
            return {}
    
    def format_prometheus_metrics(self):
        """Format collected metrics in Prometheus exposition format"""
        output = []
        system_info = self.get_system_info()
        
        for gpu_id, gpu_metrics in self.metrics.items():
            labels = f'gpu_id="{gpu_id}",hostname="{self.hostname}"'
            
            # Add system info labels
            if system_info:
                labels += f',driver_version="{system_info.get("driver_version", "unknown")}"'
                labels += f',dcgm_version="{system_info.get("dcgm_version", "unknown")}"'
            
            for field_id, value in gpu_metrics.items():
                if value is None:
                    continue
                
                # Get field name
                field_meta = dcgm_fields.DcgmFieldGetById(field_id)
                metric_name = f"dcgm_{field_meta.tag.lower()}"
                
                # Format value
                if isinstance(value, (int, float)):
                    output.append(f"{metric_name}{{{labels}}} {value}")
        
        return "\n".join(output) + "\n"
    
    def cleanup(self):
        """Cleanup DCGM resources"""
        try:
            if self.group_id:
                self.group_id.Delete()
            if self.dcgm_handle:
                pydcgm.Shutdown()
        except Exception as e:
            print(f"Error during cleanup: {e}")


class MetricsHandler(BaseHTTPRequestHandler):
    collector = None
    
    def do_GET(self):
        if self.path == '/metrics':
            self.send_response(200)
            self.send_header('Content-type', 'text/plain; version=0.0.4')
            self.end_headers()
            
            metrics = self.collector.format_prometheus_metrics()
            self.wfile.write(metrics.encode())
        else:
            self.send_response(404)
            self.end_headers()
    
    def log_message(self, format, *args):
        # Suppress default logging
        pass


def metrics_collection_loop(collector, interval=5):
    """Background thread to collect metrics periodically"""
    while True:
        try:
            collector.collect_metrics()
            time.sleep(interval)
        except Exception as e:
            print(f"Error in collection loop: {e}")
            time.sleep(interval)


def main():
    print("Starting GPU Telemetry Agent...")
    
    # Initialize collector
    collector = MetricsCollector()
    collector.initialize_dcgm()
    
    # Set collector for handler
    MetricsHandler.collector = collector
    
    # Start metrics collection thread
    collection_thread = Thread(
        target=metrics_collection_loop,
        args=(collector, 5),
        daemon=True
    )
    collection_thread.start()
    
    # Start HTTP server
    server_address = ('', 8080)
    httpd = HTTPServer(server_address, MetricsHandler)
    
    print("Telemetry agent running on port 8080")
    print("Metrics available at http://localhost:8080/metrics")
    
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        collector.cleanup()


if __name__ == '__main__':
    main()