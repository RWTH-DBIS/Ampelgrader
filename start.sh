#!/bin/bash
python3 manage.py migrate
python3 manage.py compilemessages
python3 -m pgqueuer install --pg-host "$NBBB_DB_HOST" --pg-database "$NBBB_DB_NAME" --pg-user "$NBBB_DB_USER" --pg-password "$NBBB_DB_PASSWD"
if [ "$NBBB_DEBUG" = 'true' ]; then
  echo "STARTING SERVER IN DEBUG MODE! DO NOT USE IN PRODUCTION!"
  export DJANGO_SUPERUSER_EMAIL=admin@example.com
  export DJANGO_SUPERUSER_USERNAME=admin
  export DJANGO_SUPERUSER_PASSWORD=admin
  python3 manage.py createsuperuser --no-input
  if [ "$NBBB_RUN_BAREMETAL" = 'true' ]; then
      exec python3 manage.py runserver 127.0.0.1:80 &
      python3 manage.py notify
      exit
  fi
  exec python3 manage.py runserver 0.0.0.0:80 &
  python3 manage.py notify
fi

python3 manage.py collectstatic --noinput

exec gunicorn -c gunicorn.conf.py nbblackbox.wsgi &
python3 manage.py notify
