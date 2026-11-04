# Reviewed offline app builder; setup primes dependencies before any user code is supplied.
ARG DSGPT_BASE_IMAGE
FROM ${DSGPT_BASE_IMAGE}
RUN apt-get update \
    && apt-get install --no-install-recommends -y g++ g++-mingw-w64-x86-64 \
       openjdk-17-jdk-headless tar \
       poppler-utils tesseract-ocr tesseract-ocr-eng python3-pil chromium python3-websocket \
       ffmpeg python3-pefile mono-utils mono-devel \
       python3-cffi python3-requests python3-srt python3-tqdm \
    && apt-get clean \
    && mkdir -p /opt/dsgpt /work \
    && dpkg-query -W > /opt/dsgpt/debian-package-versions.txt \
    && useradd --uid 1000 --create-home --shell /usr/sbin/nologin dsgpt \
    && chown 1000:1000 /work
COPY toolchain_install.py app_builder.py app_build_worker.py asset_install.py \
     asset_worker.py transcript_merge.py ExportFunctions.java /opt/dsgpt/
ENV ANDROID_HOME=/opt/android JAVA_TOOL_OPTIONS="-XX:ActiveProcessorCount=2" \
    GRADLE_USER_HOME=/opt/dsgpt/gradle-home
RUN python3 -I /opt/dsgpt/toolchain_install.py /opt \
    && python3 -I /opt/dsgpt/asset_install.py /opt \
    && python3 -I /opt/dsgpt/app_builder.py /opt/dsgpt/cache-project \
    && cd /opt/dsgpt/cache-project/android \
    && /opt/gradle/gradle-8.13/bin/gradle --no-daemon --max-workers=2 --console=plain \
       assembleDebug testDebugUnitTest lintDebug \
    && rm -rf /opt/downloads /opt/dsgpt/cache-project /root/.android \
       /opt/dsgpt/gradle-home/daemon /opt/dsgpt/gradle-home/workers \
    && find /opt/dsgpt/gradle-home -name '*.lock' -delete \
    && chmod -R a+rX /opt/android /opt/gradle /opt/dsgpt /opt/ghidra /opt/jdk \
       /opt/apktool /opt/jadx /opt/voice-model /opt/voice-python
LABEL org.dsgpt.purpose="offline-isolated-build"
USER 1000:1000
WORKDIR /work
ENTRYPOINT ["python3", "-I"]
