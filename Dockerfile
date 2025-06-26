FROM python:3.10
LABEL authors="Laurenz Neumann, Yue Yin"

HEALTHCHECK --interval=10s --timeout=10s \
  CMD curl -f http://0.0.0.0/grader/ping || exit 1

RUN mkdir nbblackbox

# create folder for static files
RUN mkdir /static

# Install gettext for compiling locale files
RUN apt-get update && apt-get install -y gettext && apt-get clean

COPY pyproject.toml nbblackbox/pyproject.toml
RUN pip install --upgrade pip
RUN (cd nbblackbox; pip install .)

COPY grader nbblackbox/grader
COPY locale nbblackbox/locale
COPY nbblackbox nbblackbox/nbblackbox

WORKDIR nbblackbox
COPY gunicorn.conf.py .
COPY start.sh .
COPY manage.py .

ENTRYPOINT ["bash", "start.sh"]
