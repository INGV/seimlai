ARG HYPODD_REF=V2.1b

FROM ghcr.io/seisscoped/container-base:ubuntu22.04_jupyterlab AS source
ARG HYPODD_REF
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc gfortran git make && \
    git clone --depth 1 --branch "${HYPODD_REF}" \
        https://github.com/fwaldhauser/HypoDD.git /opt/HypoDD && \
    rm -rf /var/lib/apt/lists/*

FROM source AS ph2dt-build
COPY ph2dt.inc /opt/HypoDD/include/ph2dt.inc
RUN cd /opt/HypoDD/src/ph2dt && make clean && make all

FROM ghcr.io/seisscoped/container-base:ubuntu22.04_jupyterlab AS ph2dt-runtime
RUN apt-get update && apt-get install -y --no-install-recommends libgfortran5 && rm -rf /var/lib/apt/lists/*
COPY --from=ph2dt-build /opt/HypoDD/src/ph2dt/ph2dt /usr/bin/ph2dt

FROM source AS hypodd-build
COPY hypoDD.inc /opt/HypoDD/include/hypoDD.inc
RUN cd /opt/HypoDD/src/hypoDD && make clean && make all

FROM ghcr.io/seisscoped/container-base:ubuntu22.04_jupyterlab AS hypodd-runtime
RUN apt-get update && apt-get install -y --no-install-recommends libgfortran5 && rm -rf /var/lib/apt/lists/*
COPY --from=hypodd-build /opt/HypoDD/src/hypoDD/hypoDD /usr/bin/hypoDD
