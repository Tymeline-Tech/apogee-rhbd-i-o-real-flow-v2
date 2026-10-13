# Apogee RHBD I/O — reproducible automation container
# Provides ngspice, Magic, Icarus Verilog, and Python scientific stack
# for SPICE sims, DRC/LVS, Verilog-A models, and pytest regression.

FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# System packages: EDA tools + Python 3 scientific stack
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        make \
        ngspice \
        magic \
        netgen \
        iverilog \
        python3 \
        python3-pip \
        python3-numpy \
        python3-pandas \
        python3-matplotlib \
        python3-pytest \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

# Copy repository into the image for a self-contained flow
COPY . /workspace

ENTRYPOINT ["/bin/bash"]
