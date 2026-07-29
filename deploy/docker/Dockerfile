FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN useradd --create-home --uid 10001 aether
WORKDIR /opt/aether
COPY dist/ /opt/aether/dist/
RUN python -m pip install --upgrade pip && \
    python -m pip install /opt/aether/dist/aether_core-0.19.2-py3-none-any.whl \
                          /opt/aether/dist/aether_tools-0.3.0-py3-none-any.whl \
                          /opt/aether/dist/aether_gateway-0.19.2-py3-none-any.whl
RUN mkdir -p /var/lib/aether && chown -R aether:aether /var/lib/aether /opt/aether
USER aether
ENV AETHER_HOME=/var/lib/aether HOST=0.0.0.0 PORT=8000
EXPOSE 8000
CMD ["aether-gateway"]
