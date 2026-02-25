FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir flask trueskill gunicorn

COPY analyzer_lib/__init__.py analyzer_lib/
COPY analyzer_lib/config.py analyzer_lib/
COPY scripts/team_balancer.py scripts/
COPY scripts/handicap_recommender.py scripts/
COPY web/ web/
COPY run_web.py player_ratings.json ./

CMD gunicorn --bind 0.0.0.0:$PORT web.app:app
