FROM nvidia/cuda:12.2.0-base-ubuntu22.04

# Install system dependencies
RUN apt-get update && apt-get install -y \
    wget \
    gnupg2 \
    software-properties-common \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Install DCGM
RUN distribution=$(. /etc/os-release;echo $ID$VERSION_ID | sed -e 's/\.//g') \
    && wget https://developer.download.nvidia.com/compute/cuda/repos/$distribution/x86_64/cuda-keyring_1.0-1_all.deb \
    && dpkg -i cuda-keyring_1.0-1_all.deb \
    && apt-get update \
    && apt-get install -y datacenter-gpu-manager \
    && rm -rf /var/lib/apt/lists/*

# DCGM Python bindings are installed with the package
# Common locations: /usr/local/dcgm/bindings, /usr/lib/x86_64-linux-gnu/dcgm, /usr/share/dcgm
# We'll add multiple potential paths
ENV PYTHONPATH=/usr/local/dcgm/bindings:/usr/lib/x86_64-linux-gnu/dcgm:/usr/share/dcgm/bindings:$PYTHONPATH

# Create app directory
WORKDIR /app

# Copy agent code
COPY agent.py /app/

# Expose metrics port
EXPOSE 8080

# Start DCGM service and run the agent
CMD nv-hostengine && sleep 2 && python3 /app/agent.py