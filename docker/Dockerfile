# Use a base image that has both Python and Node.js
FROM python:3.9-slim

# Install necessary tools (including bash, node, npm, and supervisor)
RUN apt-get update && apt-get install -y \
    bash \
    supervisor \
    git \
    build-essential \
    swig \
    subversion \ 
    procps \
    libopus-dev \
    ffmpeg && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Build pjsip    
RUN git clone --depth 1 --branch 2.14.1 https://github.com/pjsip/pjproject.git /tmp/pjproject
COPY /docker/user.mak /tmp/pjproject

WORKDIR /tmp/pjproject

RUN set -xe \
    && ./configure --enable-shared --disable-libwebrtc \
    && make \
    && make dep \
    && make install \
    && cd pjsip-apps/src/swig \
    && make python \
    && make -C python install \
    && cd / \
    && rm -rf /tmp/pjproject

# Set up working directory for App
WORKDIR /workspace

# Copy app source code
COPY app /workspace/app

# Create log folder
RUN mkdir /workspace/logs

# Run Pip 
RUN pip install --no-cache-dir -r /workspace/app/requirements.txt

# Configure supervisord to manage both Flask and Node.js
COPY supervisord.conf /workspace/supervisord.conf

# Expose the necessary ports
EXPOSE 5060

# Set LD_LIBRARY_PATH
#ENV LD_LIBRARY_PATH=/usr/local/lib:$LD_LIBRARY_PATH
ENV LD_LIBRARY_PATH=/usr/local/lib

# Run supervisord to manage both Flask and Node.js processes
CMD ["supervisord", "-c", "/workspace/supervisord.conf"]

# Placeholder command
#CMD ["tail", "-f", "/dev/null"]
