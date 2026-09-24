FROM apache/spark:3.5.9-scala2.12-java17-python3-ubuntu

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3-numpy python3-scipy \
    && rm -rf /var/lib/apt/lists/*

USER 185
