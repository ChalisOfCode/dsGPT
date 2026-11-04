# Dedicated offline Android fixture toolchain; inputs are publisher-verified first.
ARG DSGPT_BASE_IMAGE
FROM ${DSGPT_BASE_IMAGE}
RUN apt-get update \
    && apt-get install --no-install-recommends -y openjdk-17-jdk-headless tar \
    && apt-get clean \
    && mkdir -p /opt/dsgpt /opt/android/build-tools /opt/android/platform /work \
    && dpkg-query -W > /opt/dsgpt/debian-package-versions.txt \
    && useradd --uid 1000 --create-home --shell /usr/sbin/nologin dsgpt \
    && chown 1000:1000 /work
COPY sdk-build-tools.zip sdk-platform.zip /opt/android/
COPY install-android-inputs.py /opt/dsgpt/
RUN python3 -I /opt/dsgpt/install-android-inputs.py \
    && chmod 755 /opt/android/build-tools/aapt2 /opt/android/build-tools/d8 \
       /opt/android/build-tools/apksigner /opt/android/build-tools/zipalign
COPY build-android-fixture.py /opt/dsgpt/
ENV JAVA_TOOL_OPTIONS="-XX:ActiveProcessorCount=2 -Xmx1024m"
LABEL org.dsgpt.purpose="offline-isolated-android-build"
USER 1000:1000
WORKDIR /work
ENTRYPOINT ["python3", "-I"]
