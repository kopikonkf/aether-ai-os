FROM node:22-bookworm
ARG AIONUI_REPOSITORY=https://github.com/iOfficeAI/AionUi.git
ARG AIONUI_REF=main
RUN apt-get update && apt-get install -y --no-install-recommends git python3 ca-certificates && rm -rf /var/lib/apt/lists/*
RUN npm install --global bun
WORKDIR /opt
RUN git clone --depth 1 --branch "${AIONUI_REF}" "${AIONUI_REPOSITORY}" aionui
COPY aionui-integration /opt/aether-integration
RUN python3 /opt/aether-integration/scripts/install_aionui_integration.py /opt/aionui --wire-router
WORKDIR /opt/aionui
RUN bun install
ENV AIONUI_HOST=0.0.0.0 AIONUI_PORT=25808
EXPOSE 25808
CMD ["bun", "run", "webui:prod:remote"]
