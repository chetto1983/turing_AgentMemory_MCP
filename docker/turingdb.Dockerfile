FROM python:3.14-slim@sha256:b877e50bd90de10af8d82c57a022fc2e0dc731c5320d762a27986facfc3355c1

RUN pip install --no-cache-dir --root-user-action=ignore turingdb==1.35 \
    && groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --home-dir /turing --shell /usr/sbin/nologin app \
    && mkdir -p /turing /tmp /run \
    && chown -R app:app /turing /tmp /run

USER app

EXPOSE 6666
ENTRYPOINT ["turingdb"]
